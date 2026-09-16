"""Redis 任务队列

orchestrator 把要投递的职位 push 进队列，
auto_job worker 持续 pop 并通过 Selenium 投递。

为什么用 Redis 而不是直接调用：
- Selenium 是阻塞的，单进程串行太慢
- Redis 让 orchestrator 可以快速返回，worker 异步处理
- 队列持久化，崩溃后可恢复
- 可以跑多个 worker 并发（不同账号）
"""
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

logger = logging.getLogger(__name__)

# Redis 键名
QUEUE_KEY = "ai-resume:jobs:pending"
PROCESSING_KEY = "ai-resume:jobs:processing"
COMPLETED_KEY = "ai-resume:jobs:completed"
FAILED_KEY = "ai-resume:jobs:failed"
STATS_KEY = "ai-resume:stats"


@dataclass
class ApplyJob:
    """一个投递任务的数据结构

    由 orchestrator 创建，auto_job worker 消费。
    """
    job_id: str
    boss_job_id: str = ""
    company: str = ""
    title: str = ""
    jd_text: str = ""
    cover_letter: str = ""
    candidate_name: str = ""
    candidate_title: str = ""
    years_experience: int = 0
    ats_score: float = 0.0
    matched_skills: list = field(default_factory=list)
    missing_skills: list = field(default_factory=list)
    resume_pdf_path: str = ""
    status: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_json(self):
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, s):
        return cls(**json.loads(s))

    @staticmethod
    def make_id():
        return f"{int(time.time())}_{uuid.uuid4().hex[:8]}"


class JobQueue:
    """Redis 队列封装"""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        if not HAS_REDIS:
            raise RuntimeError("redis-py not installed. Run: pip install redis")
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.redis.ping()
        logger.info(f"Connected to Redis at {redis_url}")

    def push(self, job: ApplyJob) -> str:
        job.job_id = job.job_id or ApplyJob.make_id()
        self.redis.lpush(QUEUE_KEY, job.to_json())
        self._update_stats("pushed", job)
        logger.info(f"Pushed job {job.job_id} ({job.company}/{job.title})")
        return job.job_id

    def pop(self, timeout: int = 5) -> Optional[ApplyJob]:
        result = self.redis.brpop(QUEUE_KEY, timeout=timeout)
        if not result:
            return None
        _, payload = result
        job = ApplyJob.from_json(payload)
        self.redis.lpush(PROCESSING_KEY, payload)
        self._update_stats("processing", job)
        return job

    def complete(self, job: ApplyJob) -> None:
        self.redis.lrem(PROCESSING_KEY, 1, job.to_json())
        self.redis.lpush(COMPLETED_KEY, job.to_json())
        self.redis.ltrim(COMPLETED_KEY, 0, 999)
        self._update_stats("completed", job)
        logger.info(f"Completed job {job.job_id}")

    def fail(self, job: ApplyJob, error: str) -> None:
        self.redis.lrem(PROCESSING_KEY, 1, job.to_json())
        failed_payload = json.dumps({**asdict(job), "error": error})
        self.redis.lpush(FAILED_KEY, failed_payload)
        self.redis.ltrim(FAILED_KEY, 0, 999)
        self._update_stats("failed", job)
        logger.error(f"Failed job {job.job_id}: {error}")

    def get_stats(self) -> dict:
        return {
            "pending": self.redis.llen(QUEUE_KEY),
            "processing": self.redis.llen(PROCESSING_KEY),
            "completed": self.redis.llen(COMPLETED_KEY),
            "failed": self.redis.llen(FAILED_KEY),
        }

    def get_recent_completed(self, limit: int = 10) -> list:
        items = self.redis.lrange(COMPLETED_KEY, 0, limit - 1)
        return [json.loads(item) for item in items]

    def _update_stats(self, event: str, job: ApplyJob) -> None:
        self.redis.hincrby(STATS_KEY, f"total_{event}", 1)
        self.redis.hincrbyfloat(STATS_KEY, "total_ats_score", job.ats_score)
        self.redis.expire(STATS_KEY, 86400 * 7)


class InMemoryQueue:
    """简单的内存队列 fallback"""

    def __init__(self):
        self._pending = []
        self._processing = {}
        self._completed = []
        self._failed = []

    def push(self, job: ApplyJob) -> str:
        job.job_id = job.job_id or ApplyJob.make_id()
        self._pending.append(job)
        return job.job_id

    def pop(self, timeout: int = 0) -> Optional[ApplyJob]:
        if not self._pending:
            return None
        job = self._pending.pop(0)
        self._processing[job.job_id] = job
        return job

    def complete(self, job: ApplyJob) -> None:
        self._processing.pop(job.job_id, None)
        self._completed.append(job)
        if len(self._completed) > 1000:
            self._completed.pop(0)

    def fail(self, job: ApplyJob, error: str) -> None:
        self._processing.pop(job.job_id, None)
        self._failed.append({**asdict(job), "error": error})


    def recent(self, limit: int = 50) -> list:
        combined = []
        for job in list(self._pending):
            d = asdict(job)
            d["status"] = "pending"
            combined.append(d)
        for job_id, job in list(self._processing.items()):
            d = asdict(job)
            d["status"] = "processing"
            combined.append(d)
        for job in list(self._completed):
            d = asdict(job)
            d["status"] = "completed"
            combined.append(d)
        for item in list(self._failed):
            combined.append(item.copy())
            combined[-1]["status"] = "failed"
        combined.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return combined[: max(1, limit)]

    def get_stats(self) -> dict:
        return {
            "pending": len(self._pending),
            "processing": len(self._processing),
            "completed": len(self._completed),
            "failed": len(self._failed),
        }


def make_queue(redis_url: Optional[str] = None):
    """工厂函数：有 Redis 用 Redis，没有用 InMemory"""
    import os
    url = redis_url or os.getenv("REDIS_URL")
    if url and HAS_REDIS:
        try:
            return JobQueue(url)
        except Exception as e:
            logger.warning(f"Redis connection failed ({e}), falling back to InMemoryQueue")
            return InMemoryQueue()
    return InMemoryQueue()
