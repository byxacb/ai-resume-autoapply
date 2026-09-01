"""Token Bucket 限流器

相比 anti-ban 的简单计数，token bucket 更精细：
- 平滑突发流量（短时间多次不会触发限流）
- 支持多维度限流（按 IP/按用户/按平台）
- 支持自动放行（令牌恢复）

参考 Redis 限流思路，但本实现是进程内（单实例），
生产环境推荐用 Redis + Lua 脚本做分布式限流。
"""
import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class Bucket:
    """一个 token bucket"""
    capacity: float         # 最大令牌数
    refill_rate: float      # 每秒补充令牌数
    tokens: float           # 当前令牌数
    last_refill: float      # 上次补充时间戳

    def try_acquire(self, n: float = 1.0) -> bool:
        now = time.time()
        elapsed = now - self.last_refill
        # 补充令牌
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def time_to_available(self, n: float = 1.0) -> float:
        """距离令牌可用还要等多久（秒）"""
        if self.tokens >= n:
            return 0.0
        needed = n - self.tokens
        return needed / self.refill_rate


class TokenBucketLimiter:
    """多 key token bucket 限流器"""

    def __init__(
        self,
        default_capacity: float = 20,
        default_refill_rate: float = 20 / 3600,  # 20/小时
    ):
        self.default_capacity = default_capacity
        self.default_refill_rate = default_refill_rate
        self._buckets: Dict[str, Bucket] = {}
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _get_or_create(self, key: str, capacity: Optional[float] = None, refill: Optional[float] = None) -> Bucket:
        if key not in self._buckets:
            cap = capacity or self.default_capacity
            rate = refill or self.default_refill_rate
            self._buckets[key] = Bucket(
                capacity=cap,
                refill_rate=rate,
                tokens=cap,  # 初始满桶
                last_refill=time.time(),
            )
        return self._buckets[key]

    async def acquire(self, key: str, n: float = 1.0) -> bool:
        bucket = self._get_or_create(key)
        async with self._locks[key]:
            return bucket.try_acquire(n)

    async def wait_for(self, key: str, n: float = 1.0, max_wait: float = 600) -> bool:
        """阻塞等待直到获取 n 个令牌（最多 max_wait 秒）"""
        deadline = time.time() + max_wait
        while time.time() < deadline:
            bucket = self._get_or_create(key)
            async with self._locks[key]:
                if bucket.try_acquire(n):
                    return True
                wait = bucket.time_to_available(n)
            await asyncio.sleep(min(wait, 10))
        return False

    def get_status(self, key: str) -> dict:
        if key not in self._buckets:
            return {"available": True, "tokens": self.default_capacity}
        bucket = self._buckets[key]
        bucket.tokens = min(bucket.capacity, bucket.tokens + (time.time() - bucket.last_refill) * bucket.refill_rate)
        bucket.last_refill = time.time()
        return {
            "available": bucket.tokens >= 1,
            "tokens": round(bucket.tokens, 2),
            "capacity": bucket.capacity,
        }


# === 装饰器 ===

def rate_limited(
    limiter: TokenBucketLimiter,
    key_func=lambda *args, **kwargs: "default",
    tokens: float = 1.0,
):
    """装饰器：自动限流

    Usage:
        limiter = TokenBucketLimiter()

        @rate_limited(limiter, key_func=lambda job_id, _: f"boss:{job_id}")
        async def apply(job_id, jd):
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            key = key_func(*args, **kwargs)
            if not await limiter.acquire(key, tokens):
                wait = limiter._get_or_create(key).time_to_available(tokens)
                logger.warning(f"Rate limited: {key}, waiting {wait:.1f}s")
                await limiter.wait_for(key, tokens)
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# === BOSS 直聘专用配置 ===

def create_boss_limiter() -> TokenBucketLimiter:
    """BOSS 风控友好型限流器配置"""
    limiter = TokenBucketLimiter(
        default_capacity=10,                # 短时突发最多 10
        default_refill_rate=20 / 3600,      # 平均 20/小时
    )
    # 各平台单独 key（如果未来加新平台）
    # 暂时用默认值
    return limiter
