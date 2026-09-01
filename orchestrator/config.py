"""统一配置

加载优先级：
    1. 环境变量（最高）
    2. .env 文件
    3. config.yaml / config.json（如果有）
    4. 默认值

涉及：
- LLM 提供商
- Resume-Matcher 后端 URL
- 匹配度阈值
- 反风控参数
- Webhook 配置
- Redis URL
"""
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:
    import yaml  # type: ignore
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """LLM 配置（透传给 Resume-Matcher 后端）"""
    provider: str = "deepseek"          # openai / anthropic / gemini / deepseek / ollama
    model: str = "deepseek-chat"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    temperature: float = 0.7
    max_tokens: int = 2000


@dataclass
class MatcherConfig:
    """简历匹配器配置"""
    base_url: str = "http://localhost:8000"
    min_match_score: float = 60.0
    high_match_score: float = 80.0
    timeout: float = 60.0


@dataclass
class AntiBanConfig:
    """反风控配置"""
    max_apply_per_hour: int = 20
    max_apply_per_day: int = 100
    max_apply_per_company: int = 3
    min_interval_seconds: int = 30
    jitter_seconds: int = 15
    work_hours_start: int = 9
    work_hours_end: int = 21


@dataclass
class QueueConfig:
    redis_url: str = "redis://localhost:6379/0"
    pending_key: str = "ai-resume:jobs:pending"
    processing_key: str = "ai-resume:jobs:processing"
    completed_key: str = "ai-resume:jobs:completed"
    failed_key: str = "ai-resume:jobs:failed"
    stats_key: str = "ai-resume:stats"


@dataclass
class ScraperConfig:
    """BOSS 抓取器配置"""
    enabled: bool = True
    cookie: str = ""
    rate_limit_seconds: float = 2.0
    default_city: str = "101010100"  # 北京


@dataclass
class OrchestratorConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    matcher: MatcherConfig = field(default_factory=MatcherConfig)
    antiban: AntiBanConfig = field(default_factory=AntiBanConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    scraper: ScraperConfig = field(default_factory=ScraperConfig)


# === Candidate Profile (新概念) ===

@dataclass
class CandidateProfile:
    id: str
    name: str
    title: str = ""
    years: int = 0
    resume_path: str = ""
    skills: List[str] = field(default_factory=list)
    contact: Dict[str, str] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self):
        return asdict(self)


class CandidateStore:
    """候选人档案存储（SQLite 持久化）

    为什么需要：多用户、多设备时共享候选人信息
    """

    def __init__(self, db_path: str = "./candidates.db"):
        self.db_path = db_path
        self._ensure_table()

    def _connect(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self):
        try:
            with self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS candidates (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        title TEXT,
                        years INTEGER,
                        resume_path TEXT,
                        skills TEXT,
                        contact TEXT,
                        created_at TEXT
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.warning(f"CandidateStore init failed: {e}")

    def save(self, profile: CandidateProfile) -> None:
        from datetime import datetime
        if not profile.created_at:
            profile.created_at = datetime.utcnow().isoformat()
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO candidates
                       (id, name, title, years, resume_path, skills, contact, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        profile.id,
                        profile.name,
                        profile.title,
                        profile.years,
                        profile.resume_path,
                        json.dumps(profile.skills, ensure_ascii=False),
                        json.dumps(profile.contact, ensure_ascii=False),
                        profile.created_at,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"CandidateStore.save failed: {e}")

    def get(self, cid: str) -> Optional[dict]:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM candidates WHERE id = ?", (cid,)
                ).fetchone()
                if not row:
                    return None
                return {
                    "id": row["id"],
                    "name": row["name"],
                    "title": row["title"] or "",
                    "years": row["years"] or 0,
                    "resume_path": row["resume_path"] or "",
                    "skills": json.loads(row["skills"] or "[]"),
                    "contact": json.loads(row["contact"] or "{}"),
                    "created_at": row["created_at"],
                }
        except Exception as e:
            logger.error(f"CandidateStore.get failed: {e}")
            return None

    def list_all(self) -> List[dict]:
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM candidates ORDER BY created_at DESC").fetchall()
                return [
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "title": row["title"] or "",
                        "years": row["years"] or 0,
                        "resume_path": row["resume_path"] or "",
                        "created_at": row["created_at"],
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"CandidateStore.list_all failed: {e}")
            return []

    def delete(self, cid: str) -> bool:
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM candidates WHERE id = ?", (cid,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"CandidateStore.delete failed: {e}")
            return False


# === Global singleton ===

CONFIG: OrchestratorConfig = OrchestratorConfig()


def load_config() -> OrchestratorConfig:
    """从环境变量加载配置"""
    global CONFIG

    # LLM
    CONFIG.llm.provider = os.getenv("LLM_PROVIDER", CONFIG.llm.provider)
    CONFIG.llm.model = os.getenv("LLM_MODEL", CONFIG.llm.model)
    CONFIG.llm.api_key = os.getenv("LLM_API_KEY", CONFIG.llm.api_key)
    CONFIG.llm.base_url = os.getenv("LLM_BASE_URL", CONFIG.llm.base_url)
    CONFIG.llm.temperature = float(os.getenv("LLM_TEMPERATURE", CONFIG.llm.temperature))

    # Matcher
    CONFIG.matcher.base_url = os.getenv("RESUME_MATCHER_URL", CONFIG.matcher.base_url)
    CONFIG.matcher.min_match_score = float(
        os.getenv("MIN_MATCH_SCORE", CONFIG.matcher.min_match_score)
    )
    CONFIG.matcher.high_match_score = float(
        os.getenv("HIGH_MATCH_SCORE", CONFIG.matcher.high_match_score)
    )

    # Anti-ban
    CONFIG.antiban.max_apply_per_hour = int(
        os.getenv("MAX_APPLY_PER_HOUR", CONFIG.antiban.max_apply_per_hour)
    )
    CONFIG.antiban.max_apply_per_day = int(
        os.getenv("MAX_APPLY_PER_DAY", CONFIG.antiban.max_apply_per_day)
    )
    CONFIG.antiban.max_apply_per_company = int(
        os.getenv("MAX_APPLY_PER_COMPANY", CONFIG.antiban.max_apply_per_company)
    )

    # Queue
    CONFIG.queue.redis_url = os.getenv("REDIS_URL", CONFIG.queue.redis_url)

    # Scraper
    CONFIG.scraper.cookie = os.getenv("BOSS_COOKIE", CONFIG.scraper.cookie)
    CONFIG.scraper.default_city = os.getenv("BOSS_CITY", CONFIG.scraper.default_city)

    logger.info(
        f"Config loaded: provider={CONFIG.llm.provider}, "
        f"min_score={CONFIG.matcher.min_match_score}, "
        f"max_per_hour={CONFIG.antiban.max_apply_per_hour}"
    )
    return CONFIG


def get_config() -> OrchestratorConfig:
    return CONFIG


def set_config(new_config: OrchestratorConfig) -> None:
    global CONFIG
    CONFIG = new_config


# Auto-load on import
load_config()
