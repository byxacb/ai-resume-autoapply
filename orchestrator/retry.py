"""指数退避重试 + 熔断器

应用场景：
- HTTP 调用偶发失败（LLM API、Resume-Matcher 后端）
- Selenium 操作偶发超时
- Redis 临时不可用

设计：
- 3 次重试，间隔 1s → 2s → 4s，加 jitter
- 熔断器：连续 5 次失败后熔断 60s
- 可重试异常分类：网络错误 vs 业务错误
"""
import asyncio
import functools
import logging
import random
import time
from typing import Any, Awaitable, Callable, Optional, Type, Union

logger = logging.getLogger(__name__)


# 默认可重试异常
DEFAULT_RETRY_EXCEPTIONS: tuple = (
    asyncio.TimeoutError,
    ConnectionError,
    TimeoutError,
)


class CircuitBreakerOpen(Exception):
    """熔断器打开时抛出"""
    pass


class CircuitBreaker:
    """简单熔断器

    States:
        CLOSED: 正常
        OPEN: 熔断中（拒绝请求）
        HALF_OPEN: 探测恢复
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        name: str = "default",
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name
        self._failures = 0
        self._opened_at: Optional[float] = None

    def _state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if time.time() - self._opened_at > self.recovery_timeout:
            return "half_open"
        return "open"

    def before(self) -> None:
        state = self._state()
        if state == "open":
            raise CircuitBreakerOpen(f"Circuit breaker '{self.name}' is OPEN")
        if state == "half_open":
            logger.info(f"Circuit breaker '{self.name}' entering HALF_OPEN")

    def on_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = time.time()
            logger.warning(
                f"Circuit breaker '{self.name}' OPENED after {self._failures} failures"
            )


_BREAKERS: dict = {}


def get_breaker(name: str) -> CircuitBreaker:
    if name not in _BREAKERS:
        _BREAKERS[name] = CircuitBreaker(name=name)
    return _BREAKERS[name]


async def retry_async(
    func: Callable[..., Awaitable[Any]],
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: tuple = DEFAULT_RETRY_EXCEPTIONS,
    breaker: Optional[CircuitBreaker] = None,
    **kwargs,
) -> Any:
    """通用异步重试

    Args:
        func: 异步函数
        max_attempts: 最大尝试次数（含首次）
        base_delay: 基础退避秒数
        max_delay: 最大退避秒数
        retry_on: 可重试异常类型
        breaker: 熔断器（可选）
    """
    if breaker:
        breaker.before()

    last_exception = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = await func(*args, **kwargs)
            if breaker:
                breaker.on_success()
            return result
        except retry_on as e:
            last_exception = e
            if attempt == max_attempts:
                if breaker:
                    breaker.on_failure()
                logger.error(
                    f"Function {func.__name__} failed after {max_attempts} attempts: {e}"
                )
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            delay = delay + random.uniform(0, delay * 0.1)  # jitter
            logger.warning(
                f"Function {func.__name__} attempt {attempt} failed: {e}; "
                f"retrying in {delay:.1f}s"
            )
            await asyncio.sleep(delay)
        except Exception as e:
            # 不可重试异常
            if breaker:
                breaker.on_failure()
            raise


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: tuple = DEFAULT_RETRY_EXCEPTIONS,
    breaker_name: Optional[str] = None,
):
    """装饰器版本

    Usage:
        @retry(max_attempts=3)
        async def fetch():
            ...
    """
    breaker = get_breaker(breaker_name) if breaker_name else None

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_async(
                func,
                *args,
                max_attempts=max_attempts,
                base_delay=base_delay,
                max_delay=max_delay,
                retry_on=retry_on,
                breaker=breaker,
                **kwargs,
            )

        return wrapper

    return decorator
