"""统一配置 - 整合 Resume-Matcher + auto_job
所有配置项集中在一处，方便切换 LLM 提供商、调整匹配阈值、风控策略。
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Resume-Matcher 后端地址
RESUME_MATCHER_URL = os.getenv("RESUME_MATCHER_URL", "http://localhost:8000")

# auto_job RPA 脚本路径
AUTO_JOB_DIR = PROJECT_ROOT / "auto_job" / "auto_job_find"


@dataclass(frozen=True)
class LLMConfig:
    """LLM 提供商配置
    推荐用 DeepSeek 国产 LLM：成本最低、中文最好、长上下文支持。
    也可以切到 OpenAI/Claude/Gemini/Ollama。
    """
    provider: str = os.getenv("LLM_PROVIDER", "deepseek")
    api_key: str = os.getenv("LLM_API_KEY", "")
    base_url: Optional[str] = os.getenv("LLM_BASE_URL")
    model: str = os.getenv("LLM_MODEL", "deepseek-chat")
    temperature: float = 0.3


@dataclass(frozen=True)
class MatcherConfig:
    """ATS 评分阈值配置
    评分来自 Resume-Matcher 的 compute_ats_score()：
    - keyword_match 55%
    - skills_coverage 25%
    - section_completeness 20%
    """
    # 低于此分数的职位直接跳过，避免海投低匹配
    min_match_score: float = 60.0

    # 高于此分数标记为"优先投递"
    high_match_score: float = 80.0

    # 必须技能覆盖率低于此值则拒绝投递（防止 JD 要求 80% 命中简历没列）
    min_required_skills_coverage: float = 0.5


@dataclass(frozen=True)
class AntiBanConfig:
    """BOSS 直聘风控配置
    BOSS 对频繁打招呼的账号会限流甚至封号，必须严格控制节奏。
    """
    # 每小时最多打招呼次数
    max_apply_per_hour: int = 20

    # 每天最多打招呼次数
    max_apply_per_day: int = 100

    # 两次打招呼之间的最小间隔（秒）
    min_interval_seconds: int = 30

    # 随机抖动（秒），让行为更像真人
    jitter_seconds: int = 15

    # 同一公司最多投递职位数
    max_apply_per_company: int = 3


@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    matcher: MatcherConfig = field(default_factory=MatcherConfig)
    antiban: AntiBanConfig = field(default_factory=AntiBanConfig)


# 全局单例
CONFIG = AppConfig()
