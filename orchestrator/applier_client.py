"""auto_job RPA 包装器 - 真实实现版

通过 Redis 队列与 auto_job worker 通信：
- push: 把任务加入 Redis 队列
- worker (auto_job_worker.py) 持续 pop 并通过 Selenium 投递

这种设计的好处：
- orchestrator 不阻塞（不用等 Selenium）
- worker 可以崩溃恢复
- 可以跑多个 worker 并发
- 完全真实的 Selenium 调用（不是占位符）
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .queue import ApplyJob, make_queue
from .config import AntiBanConfig

logger = logging.getLogger(__name__)


@dataclass
class ApplyRecord:
    job_id: str
    job_title: str
    company: str
    jd_text: str
    cover_letter: str
    ats_score: float
    applied_at: datetime
    success: bool
    error: str = ""


@dataclass
class ApplyStats:
    applied_today: list = field(default_factory=list)
    applied_this_hour: list = field(default_factory=list)
    applied_per_company: dict = field(default_factory=dict)


class ApplierClient:
    """auto_job RPA 包装器

    通过 Redis 队列与 auto_job_worker.py 通信。
    worker 端会用真实的 Selenium + undetected-chromedriver 投递。
    """

    def __init__(self, antiban: Optional[AntiBanConfig] = None, redis_url: Optional[str] = None):
        self.antiban = antiban or AntiBanConfig()
        self.stats = ApplyStats()
        self.queue = make_queue(redis_url)
        logger.info(f"ApplierClient initialized, queue stats: {self.queue.get_stats()}")

    def check_rate_limit(self, company: str) -> tuple:
        now = datetime.now()
        self.stats.applied_this_hour = [
            t for t in self.stats.applied_this_hour
            if now - t < timedelta(hours=1)
        ]
        if len(self.stats.applied_this_hour) >= self.antiban.max_apply_per_hour:
            return False, f"Hourly limit reached ({self.antiban.max_apply_per_hour})"
        today_count = sum(
            1 for r in self.stats.applied_today if r.applied_at.date() == now.date()
        )
        if today_count >= self.antiban.max_apply_per_day:
            return False, f"Daily limit reached ({self.antiban.max_apply_per_day})"
        company_count = self.stats.applied_per_company.get(company, 0)
        if company_count >= self.antiban.max_apply_per_company:
            return False, f"Company limit reached ({company})"
        return True, ""

    def record_apply(self, record: ApplyRecord) -> None:
        self.stats.applied_today.append(record)
        self.stats.applied_this_hour.append(record.applied_at)
        self.stats.applied_per_company[record.company] = (
            self.stats.applied_per_company.get(record.company, 0) + 1
        )

    def apply(
        self,
        job_id: str,
        job_title: str,
        company: str,
        jd_text: str,
        cover_letter: str,
        candidate_name: str = "",
        candidate_title: str = "",
        years_experience: int = 0,
        matched_skills: list = None,
        missing_skills: list = None,
        ats_score: float = 0.0,
    ) -> ApplyRecord:
        """通过 Redis 队列把任务交给 auto_job worker

        Args:
            job_id: 唯一任务 ID
            job_title: 职位名
            company: 公司名
            jd_text: 职位描述
            cover_letter: AI 生成的求职信
            candidate_name: 候选人姓名
            candidate_title: 候选人目标岗位
            years_experience: 工作年限
            matched_skills: 简历匹配的技能
            missing_skills: 简历缺失的技能
            ats_score: ATS 评分

        Returns:
            ApplyRecord with success=False (因为投递是异步的)
        """
        now = datetime.now()
        record = ApplyRecord(
            job_id=job_id,
            job_title=job_title,
            company=company,
            jd_text=jd_text,
            cover_letter=cover_letter,
            ats_score=ats_score,
            applied_at=now,
            success=False,
        )

        allowed, reason = self.check_rate_limit(company)
        if not allowed:
            record.error = reason
            logger.warning(f"Rate limit blocked {company}/{job_title}: {reason}")
            return record

        # 构造任务并 push 到 Redis
        apply_job = ApplyJob(
            job_id=job_id,
            boss_job_id=job_id,
            company=company,
            title=job_title,
            jd_text=jd_text,
            cover_letter=cover_letter,
            candidate_name=candidate_name,
            candidate_title=candidate_title,
            years_experience=years_experience,
            ats_score=ats_score,
            matched_skills=matched_skills or [],
            missing_skills=missing_skills or [],
        )

        try:
            queue_id = self.queue.push(apply_job)
            record.success = True  # 任务已成功入队
            logger.info(f"Queued job {queue_id} for {company}/{job_title}")
        except Exception as e:
            record.error = f"Queue push failed: {e}"
            logger.error(f"Failed to queue job: {e}")

        self.record_apply(record)
        return record

    def get_stats_summary(self) -> dict:
        return {
            "applied_today_count": len(self.stats.applied_today),
            "applied_this_hour_count": len(self.stats.applied_this_hour),
            "remaining_hourly": self.antiban.max_apply_per_hour - len(self.stats.applied_this_hour),
            "remaining_daily": self.antiban.max_apply_per_day - len(self.stats.applied_today),
            "companies_today": dict(self.stats.applied_per_company),
            "queue_stats": self.queue.get_stats(),
        }
