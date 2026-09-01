"""包装 auto_job RPA 的客户端

把 Selenium 浏览器自动化抽象成 Python API，方便 orchestrator 调用。
这一层主要是包装，避免 orchestrator 直接依赖 auto_job 的内部实现。
"""
import logging
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .config import AUTO_JOB_DIR, AntiBanConfig

logger = logging.getLogger(__name__)


@dataclass
class ApplyRecord:
    """单次投递记录"""
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
    """投递统计（用于风控）"""
    applied_today: list[ApplyRecord] = field(default_factory=list)
    applied_this_hour: list[datetime] = field(default_factory=list)
    applied_per_company: dict[str, int] = field(default_factory=dict)


class ApplierClient:
    """auto_job RPA 包装器

    当前实现是 subprocess 调 Python 脚本（最简方式）。
    未来可以把 Selenium 代码直接 import 进来，更高效。
    """

    def __init__(self, antiban: AntiBanConfig | None = None):
        self.antiban = antiban or AntiBanConfig()
        self.stats = ApplyStats()
        self._verify_setup()

    def _verify_setup(self) -> None:
        """检查 auto_job 是否就绪"""
        if not AUTO_JOB_DIR.exists():
            raise FileNotFoundError(
                f"auto_job not found at {AUTO_JOB_DIR}. "
                f"Make sure you cloned byxacb/auto_job__find__chatgpt__rpa."
            )
        req_file = AUTO_JOB_DIR / "requirements.txt"
        if not req_file.exists():
            raise FileNotFoundError(f"requirements.txt not found at {req_file}")

    def check_rate_limit(self, company: str) -> tuple[bool, str]:
        """检查是否触发风控阈值

        Returns:
            (allowed, reason) - 是否允许投递，不允许的原因
        """
        now = datetime.now()

        # 清理一小时前的记录
        self.stats.applied_this_hour = [
            t for t in self.stats.applied_this_hour
            if now - t < timedelta(hours=1)
        ]

        # 检查小时配额
        if len(self.stats.applied_this_hour) >= self.antiban.max_apply_per_hour:
            return False, f"Hourly limit reached ({self.antiban.max_apply_per_hour})"

        # 检查日配额
        today_count = sum(
            1 for r in self.stats.applied_today
            if r.applied_at.date() == now.date()
        )
        if today_count >= self.antiban.max_apply_per_day:
            return False, f"Daily limit reached ({self.antiban.max_apply_per_day})"

        # 检查同公司配额
        company_count = self.stats.applied_per_company.get(company, 0)
        if company_count >= self.antiban.max_apply_per_company:
            return False, f"Company limit reached ({company})"

        return True, ""

    def record_apply(self, record: ApplyRecord) -> None:
        """记录一次投递"""
        self.stats.applied_today.append(record)
        self.stats.applied_this_hour.append(record.applied_at)
        self.stats.applied_per_company[record.company] = (
            self.stats.applied_per_company.get(record.company, 0) + 1
        )

    def wait_for_rate_limit(self) -> None:
        """等待直到可以投递（带随机抖动）"""
        base_wait = self.antiban.min_interval_seconds
        jitter = random.randint(0, self.antiban.jitter_seconds)
        total = base_wait + jitter
        logger.info(f"Sleeping {total}s before next apply (anti-ban)")
        time.sleep(total)

    def apply(
        self,
        job_id: str,
        job_title: str,
        company: str,
        jd_text: str,
        cover_letter: str,
    ) -> ApplyRecord:
        """通过 BOSS 直聘 RPA 投递一个职位

        注意：当前实现是占位符。完整实现需要：
        1. 启动 Selenium 浏览器（已经登录）
        2. 在 BOSS 上搜索职位
        3. 打开职位详情
        4. 粘贴 cover_letter 到聊天框
        5. 点击"立即沟通"按钮

        Args:
            job_id: 职位唯一 ID
            job_title: 职位名称
            company: 公司名
            jd_text: 职位描述
            cover_letter: AI 生成的求职信

        Returns:
            ApplyRecord 投递结果
        """
        now = datetime.now()
        record = ApplyRecord(
            job_id=job_id,
            job_title=job_title,
            company=company,
            jd_text=jd_text,
            cover_letter=cover_letter,
            ats_score=0.0,  # 由 caller 填充
            applied_at=now,
            success=False,
        )

        # 频率控制
        allowed, reason = self.check_rate_limit(company)
        if not allowed:
            record.error = reason
            logger.warning(f"Rate limit blocked apply to {company}/{job_title}: {reason}")
            return record

        try:
            # TODO: 实际调用 auto_job 的 Selenium 逻辑
            # 这里应该直接 import finding_jobs 和 write_response
            # 或者通过消息队列（Redis/RabbitMQ）传给 auto_job 进程
            #
            # 简化版：写一个临时脚本，传 JD 和求职信进去
            self._invoke_auto_job_apply(jd_text, cover_letter)
            record.success = True
            logger.info(f"Applied to {company}/{job_title}")
        except Exception as e:
            record.error = str(e)
            logger.error(f"Apply failed for {company}/{job_title}: {e}")

        self.record_apply(record)
        return record

    def _invoke_auto_job_apply(self, jd_text: str, cover_letter: str) -> None:
        """调用 auto_job 的实际投递逻辑

        这是一个 subprocess 占位实现。生产环境应该：
        1. 启动一个长期运行的 Selenium 服务
        2. 通过 IPC/RPC 调用 apply(jd, letter)
        3. 保持浏览器会话，避免重复登录
        """
        # 把 JD 和求职信写到临时文件
        tmp_jd = AUTO_JOB_DIR / "_tmp_jd.txt"
        tmp_letter = AUTO_JOB_DIR / "_tmp_letter.txt"
        tmp_jd.write_text(jd_text, encoding="utf-8")
        tmp_letter.write_text(cover_letter, encoding="utf-8")

        logger.warning(
            "_invoke_auto_job_apply is a placeholder. "
            "See docs/BOSS_RPA_NOTES.md for the real implementation."
        )
        # 实际调用示例（需要先实现 apply_one.py 包装脚本）：
        # subprocess.run(
        #     [sys.executable, "apply_one.py", str(tmp_jd), str(tmp_letter)],
        #     cwd=AUTO_JOB_DIR,
        #     check=True,
        #     timeout=60,
        # )

    def get_stats_summary(self) -> dict:
        """获取当前风控统计"""
        return {
            "applied_today_count": len(self.stats.applied_today),
            "applied_this_hour_count": len(self.stats.applied_this_hour),
            "remaining_hourly": self.antiban.max_apply_per_hour - len(self.stats.applied_this_hour),
            "remaining_daily": self.antiban.max_apply_per_day - len(self.stats.applied_today),
            "companies_today": dict(self.stats.applied_per_company),
        }
