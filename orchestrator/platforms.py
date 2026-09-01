"""多平台适配器（抽象层 + 各平台实现）

支持的平台：
- BOSS 直聘 (scraper.py)
- 拉勾网 (lagou.py)
- 猎聘 (liepin.py)
- 智联招聘 (zhilian.py) [stub]

为什么抽象：
- 不同平台 JD 结构不同（BOSS 短，拉勾长）
- 不同平台登录方式不同（BOSS 微信，拉勾扫码，猎聘邮箱）
- 不同平台投递 API 不同
- 统一抽象后，orchestrator 不关心平台
"""
import abc
import asyncio
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """统一的职位数据结构（平台无关）"""
    job_id: str
    platform: str
    title: str
    company: str
    city: str = ""
    salary: str = ""
    experience: str = ""
    education: str = ""
    jd_text: str = ""
    url: str = ""
    tags: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class PlatformAdapter(abc.ABC):
    """平台适配器抽象基类"""

    name: str = "unknown"

    @abc.abstractmethod
    async def search(
        self,
        query: str,
        city: str = "",
        max_jobs: int = 30,
    ) -> List[Job]:
        """搜索职位"""
        ...

    @abc.abstractmethod
    async def fetch_jd(self, job_id: str) -> str:
        """获取职位详情"""
        ...

    async def search_with_jd(
        self,
        query: str,
        city: str = "",
        max_jobs: int = 30,
    ) -> List[Job]:
        """搜索 + 抓 JD"""
        jobs = await self.search(query, city=city, max_jobs=max_jobs)
        for job in jobs:
            if not job.jd_text:
                job.jd_text = await self.fetch_jd(job.job_id)
        return jobs


# === 拉勾网适配器 ===

class LagouAdapter(PlatformAdapter):
    name = "lagou"

    CITY_MAP = {
        "北京": "010",
        "上海": "020",
        "广州": "030",
        "深圳": "040",
        "杭州": "080",
        "成都": "090",
    }

    def __init__(self, cookie: Optional[str] = None):
        self.cookie = cookie or ""
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.lagou.com/wn/jobs",
                "Accept": "application/json, text/plain, */*",
                **({"Cookie": self.cookie} if self.cookie else {}),
            },
            timeout=30,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._client.aclose()

    async def search(
        self,
        query: str,
        city: str = "北京",
        max_jobs: int = 30,
    ) -> List[Job]:
        city_code = self.CITY_MAP.get(city, city)
        try:
            resp = await self._client.post(
                "https://www.lagou.com/wn/jobs/positionAjax.json",
                json={
                    "first": True,
                    "pn": 1,
                    "kd": query,
                    "city": city_code,
                    "needAddtionalResult": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Lagou search failed: {e}")
            return []

        jobs = []
        for item in data.get("content", {}).get("positionResult", {}).get("result", []):
            try:
                jobs.append(
                    Job(
                        job_id=str(item.get("positionId", "")),
                        platform=self.name,
                        title=item.get("positionName", ""),
                        company=item.get("companyFullName", ""),
                        city=item.get("city", ""),
                        salary=item.get("salary", ""),
                        experience=item.get("workYear", ""),
                        education=item.get("education", ""),
                        url=f"https://www.lagou.com/wn/jobs/{item.get('positionId')}.html",
                        raw=item,
                    )
                )
            except Exception as e:
                logger.warning(f"Lagou job parse failed: {e}")
        return jobs[:max_jobs]

    async def fetch_jd(self, job_id: str) -> str:
        try:
            resp = await self._client.get(
                f"https://www.lagou.com/wn/jobs/{job_id}.html",
            )
            resp.raise_for_status()
            html = resp.text
            # 简化的 JD 提取：找职位描述块
            import re
            m = re.search(r'job-detail.*?</div>', html, re.DOTALL)
            if m:
                # 粗略提取 <p> 标签
                ps = re.findall(r'<p[^>]*>(.*?)</p>', m.group(0), re.DOTALL)
                jd = "\n".join(re.sub(r'<[^>]+>', '', p).strip() for p in ps if p.strip())
                return jd
        except Exception as e:
            logger.error(f"Lagou JD fetch failed: {e}")
        return ""


# === 猎聘适配器 ===

class LiepinAdapter(PlatformAdapter):
    name = "liepin"

    def __init__(self, cookie: Optional[str] = None):
        self.cookie = cookie or ""
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.liepin.com/zhaopin",
                **({"Cookie": self.cookie} if self.cookie else {}),
            },
            timeout=30,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._client.aclose()

    async def search(
        self,
        query: str,
        city: str = "410",
        max_jobs: int = 30,
    ) -> List[Job]:
        """city: 410=北京, 020=上海, 050=广州, 080=深圳"""
        try:
            resp = await self._client.get(
                "https://api-c.liepin.com/api/com.liepin.searchfront4c.search-searchJobsByCondition",
                params={
                    "query": query,
                    "city": city,
                    "pageSize": 15,
                    "currentPage": 0,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Liepin search failed: {e}")
            return []

        jobs = []
        for item in data.get("data", {}).get("jobCardList", []):
            try:
                job = Job(
                    job_id=str(item.get("jobId", "")),
                    platform=self.name,
                    title=item.get("jobTitle", ""),
                    company=item.get("compName", ""),
                    salary=item.get("salary", ""),
                    city=item.get("city", ""),
                    experience=item.get("workYear", ""),
                    education=item.get("eduLevel", ""),
                    tags=item.get("labels", []),
                    url=f"https://www.liepin.com/job/{item.get('jobId')}.shtml",
                    raw=item,
                )
                # 抓 JD 文本（如果有 inline 字段）
                job.jd_text = item.get("describe", "") or item.get("jobDesc", "")
                jobs.append(job)
            except Exception as e:
                logger.warning(f"Liepin job parse failed: {e}")
        return jobs[:max_jobs]

    async def fetch_jd(self, job_id: str) -> str:
        try:
            resp = await self._client.get(
                f"https://api-c.liepin.com/api/com.liepin.searchfront4c.search-jobDetail",
                params={"jobId": job_id},
            )
            resp.raise_for_status()
            data = resp.json()
            job = data.get("data", {}).get("job", {})
            return job.get("describe", "") or job.get("jobDesc", "")
        except Exception as e:
            logger.error(f"Liepin JD fetch failed: {e}")
        return ""


# === 智联 stub（待实现）===

class ZhilianAdapter(PlatformAdapter):
    name = "zhilian"

    async def search(self, query, city="", max_jobs=30):
        logger.warning("Zhilian adapter not yet implemented")
        return []

    async def fetch_jd(self, job_id):
        return ""


# === Factory ===

def get_adapter(platform: str, cookie: Optional[str] = None) -> PlatformAdapter:
    """根据平台名获取适配器"""
    adapters = {
        "lagou": LagouAdapter,
        "liepin": LiepinAdapter,
        "zhilian": ZhilianAdapter,
    }
    cls = adapters.get(platform.lower())
    if not cls:
        raise ValueError(f"Unknown platform: {platform}. Supported: {list(adapters.keys())}")
    return cls(cookie=cookie)


async def search_all_platforms(
    query: str,
    city: str = "",
    platforms: Optional[List[str]] = None,
    max_per_platform: int = 20,
    cookies: Optional[Dict[str, str]] = None,
) -> List[Job]:
    """跨平台搜索"""
    platforms = platforms or ["lagou", "liepin"]
    cookies = cookies or {}

    async def _search_one(p):
        try:
            async with get_adapter(p, cookies.get(p)) as adapter:
                jobs = await adapter.search_with_jd(query, city=city, max_jobs=max_per_platform)
                logger.info(f"{p}: found {len(jobs)} jobs")
                return jobs
        except Exception as e:
            logger.error(f"{p} search failed: {e}")
            return []

    results = await asyncio.gather(*[_search_one(p) for p in platforms])
    all_jobs = []
    for jobs in results:
        all_jobs.extend(jobs)
    return all_jobs
