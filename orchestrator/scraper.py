"""BOSS 直聘职位抓取器（无 Selenium 版本）

使用 BOSS 的公开 API/JSON 接口而非 Selenium：
- 列表 API：https://www.zhipin.com/wapi/zpgeek/search/joblist.json
- 详情 API：https://www.zhipin.com/wapi/zpgeek/job/detail.json
- 城市代码：https://www.zhipin.com/wapi/zpCommon/getCityList.json

相对 Selenium 版的优势：
- 不需要浏览器，不需要登录（搜索公开）
- 速度快 10-100x
- 风控更低
- 内存占用低

限制：
- 部分 BOSS 高级筛选要求登录态
- 频率限制更严格（建议 ≤ 1 req/sec）

如果 BOSS 接口变动或被风控，fallback 到 Selenium 版（boss_selenium_scraper.py）
"""
import asyncio
import json
import logging
import random
import time
from dataclasses import asdict, dataclass, field
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.zhipin.com"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.zhipin.com/web/geek/job",
}


@dataclass
class JobListing:
    """一个 BOSS 职位的简略信息"""
    boss_job_id: str
    title: str
    company: str
    salary: str
    city: str
    experience: str
    education: str
    company_industry: str = ""
    job_description: str = ""
    url: str = ""

    def to_dict(self):
        return asdict(self)


class BossScraper:
    """BOSS 直聘 API 抓取器"""

    def __init__(
        self,
        cookie: Optional[str] = None,
        rate_limit_seconds: float = 2.0,
        timeout: float = 30.0,
    ):
        self.cookie = cookie or ""
        self.rate_limit_seconds = rate_limit_seconds
        self._last_request = 0.0
        self._client = httpx.AsyncClient(
            headers={**DEFAULT_HEADERS, **({"Cookie": self.cookie} if self.cookie else {})},
            timeout=timeout,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._client.aclose()

    async def _throttle(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit_seconds:
            wait = self.rate_limit_seconds - elapsed + random.uniform(0, 0.5)
            await asyncio.sleep(wait)
        self._last_request = time.time()

    async def search_jobs(
        self,
        query: str,
        city: str = "101010100",
        page: int = 1,
        page_size: int = 30,
    ) -> List[JobListing]:
        """搜索职位

        Args:
            query: 关键词，如 "iOS 开发"
            city: 城市代码（默认北京 101010100）
            page: 页码
            page_size: 每页数量
        """
        await self._throttle()
        params = {
            "query": query,
            "city": city,
            "page": page,
            "pageSize": page_size,
        }
        try:
            resp = await self._client.get(
                f"{BASE_URL}/wapi/zpgeek/search/joblist.json",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"BOSS search failed: {e}")
            return []

        jobs = []
        if data.get("code") != 0:
            logger.warning(f"BOSS returned code {data.get('code')}: {data.get('message')}")
            return []

        for item in data.get("data", {}).get("jobList", []):
            try:
                jobs.append(
                    JobListing(
                        boss_job_id=str(item.get("encryptId", item.get("jobId", ""))),
                        title=item.get("jobName", ""),
                        company=item.get("companyName", ""),
                        salary=item.get("salaryDesc", ""),
                        city=item.get("cityName", ""),
                        experience=item.get("jobExperience", ""),
                        education=item.get("jobDegree", ""),
                        company_industry=item.get("brandIndustry", ""),
                        url=f"{BASE_URL}/web/geek/job/{item.get('encryptId', '')}",
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to parse job: {e}")
                continue

        logger.info(f"BOSS search '{query}' page {page}: {len(jobs)} jobs")
        return jobs

    async def fetch_jd(self, boss_job_id: str) -> str:
        """获取职位详情/描述

        Args:
            boss_job_id: BOSS 加密职位 ID（来自 search_jobs）
        """
        await self._throttle()
        try:
            resp = await self._client.get(
                f"{BASE_URL}/wapi/zpgeek/job/detail.json",
                params={"jobId": boss_job_id},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"BOSS JD fetch failed: {e}")
            return ""

        if data.get("code") != 0:
            return ""

        job_info = data.get("data", {}).get("jobInfo", {})
        desc = job_info.get("postDescription", "") or job_info.get("jobDesc", "")
        return desc

    async def fetch_jd_for_listing(self, listing: JobListing) -> JobListing:
        """Convenience: 给简略 listing 抓完整 JD"""
        jd = await self.fetch_jd(listing.boss_job_id)
        listing.job_description = jd
        return listing

    async def search_with_jd(
        self,
        query: str,
        city: str = "101010100",
        max_jobs: int = 30,
        pages: int = 2,
    ) -> List[JobListing]:
        """搜索并抓 JD，返回完整职位列表

        适合 orchestrator 一次性消费。
        """
        all_jobs = []
        for page in range(1, pages + 1):
            listings = await self.search_jobs(query, city=city, page=page, page_size=15)
            if not listings:
                break
            for listing in listings:
                if len(all_jobs) >= max_jobs:
                    return all_jobs
                listing = await self.fetch_jd_for_listing(listing)
                if listing.job_description:
                    all_jobs.append(listing)
        return all_jobs


# === Utility ===

# 常用城市代码
CITY_CODES = {
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "成都": "101270100",
    "南京": "101190100",
    "武汉": "101200100",
    "西安": "101110100",
    "苏州": "101190400",
    "厦门": "101230200",
    "长沙": "101250100",
    "天津": "101030100",
    "重庆": "101040100",
    "青岛": "101120200",
}


async def quick_scrape(query: str, city: str = "北京", max_jobs: int = 20) -> List[dict]:
    """Quick helper: scrape BOSS for given query and city name (Chinese).

    Example:
        jobs = await quick_scrape("iOS 开发", city="北京", max_jobs=10)
    """
    city_code = CITY_CODES.get(city, city)
    async with BossScraper() as scraper:
        listings = await scraper.search_with_jd(query, city=city_code, max_jobs=max_jobs)
    return [j.to_dict() for j in listings]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    jobs = asyncio.run(quick_scrape("iOS 开发", "北京", max_jobs=5))
    print(json.dumps(jobs, ensure_ascii=False, indent=2))
