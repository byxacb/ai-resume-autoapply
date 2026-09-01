"""调用 Resume-Matcher 后端的 HTTP 客户端

封装了上传简历、解析 JD、获取 ATS 评分、改写简历、生成求职信等核心 API。
"""
import logging
from pathlib import Path
from typing import Any

import httpx

from .config import RESUME_MATCHER_URL

logger = logging.getLogger(__name__)


class MatcherClient:
    """Resume-Matcher API 客户端"""

    def __init__(self, base_url: str = RESUME_MATCHER_URL, timeout: float = 240.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "MatcherClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def health(self) -> dict[str, Any]:
        """检查 Resume-Matcher 后端是否健康"""
        resp = await self._client.get("/api/v1/health")
        resp.raise_for_status()
        return resp.json()

    async def upload_resume(self, file_path: str | Path) -> dict[str, Any]:
        """上传 PDF/DOCX 简历，返回 resume_id"""
        file_path = Path(file_path)
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "application/octet-stream")}
            resp = await self._client.post("/api/v1/resumes/upload", files=files)
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Resume uploaded: id={data.get('id')}")
        return data

    async def upload_job_description(self, jd_text: str) -> dict[str, Any]:
        """上传 JD 文本，返回 job_id"""
        resp = await self._client.post(
            "/api/v1/jobs/upload",
            json={"content": jd_text},
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"JD uploaded: id={data.get('id')}")
        return data

    async def improve_preview(
        self, resume_id: str, job_id: str, prompt_id: str = "keywords"
    ) -> dict[str, Any]:
        """触发简历改写预览，返回 ATS 评分和改进后的内容
        这是核心 API，包含：
        - 关键词匹配度
        - 技能覆盖率
        - 段落完整度
        - 总体 ATS 评分
        - 缺失关键词列表
        """
        resp = await self._client.post(
            "/api/v1/resumes/improve/preview",
            json={
                "resume_id": resume_id,
                "job_id": job_id,
                "prompt_id": prompt_id,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            f"Improve preview done: score={data.get('ats_score', {}).get('overall_score', '?')}"
        )
        return data

    async def improve_confirm(
        self, resume_id: str, job_id: str, preview_hash: str
    ) -> dict[str, Any]:
        """确认改写，返回最终优化的简历"""
        resp = await self._client.post(
            "/api/v1/resumes/improve/confirm",
            json={
                "resume_id": resume_id,
                "job_id": job_id,
                "preview_hash": preview_hash,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def generate_cover_letter(
        self, resume_id: str, job_id: str
    ) -> str:
        """生成求职信（带匹配度引用）"""
        resp = await self._client.post(
            f"/api/v1/resumes/{resume_id}/cover-letter",
            json={"job_id": job_id},
        )
        resp.raise_for_status()
        return resp.json().get("cover_letter", "")

    async def get_resume_pdf(self, resume_id: str) -> bytes:
        """获取优化后的简历 PDF（用于 BOSS 投递时附带的简历）"""
        resp = await self._client.get(f"/api/v1/resumes/{resume_id}/pdf")
        resp.raise_for_status()
        return resp.content


def extract_match_score(preview: dict[str, Any]) -> dict[str, Any]:
    """从 improve_preview 响应中提取评分字段
    返回结构：
    {
        "overall_score": 75.5,
        "keyword_match": 80.0,
        "skills_coverage": 70.0,
        "section_completeness": 65.0,
        "missing_keywords": ["kubernetes", "grpc"],
        "matched_keywords": ["python", "fastapi"],
    }
    """
    ats = preview.get("ats_score", {})
    keywords = preview.get("job_keywords", {})
    refined = preview.get("refined_resume", {})

    jd_skills = set(keywords.get("required_skills", []) + keywords.get("preferred_skills", []))
    resume_skills = set(refined.get("additional", {}).get("technicalSkills", []))
    matched = jd_skills & resume_skills
    missing = jd_skills - resume_skills

    return {
        "overall_score": ats.get("overall_score", 0.0),
        "keyword_match": ats.get("sub_scores", {}).get("keyword_match", 0.0),
        "skills_coverage": ats.get("sub_scores", {}).get("skills_coverage", 0.0),
        "section_completeness": ats.get("sub_scores", {}).get("section_completeness", 0.0),
        "missing_keywords": list(missing),
        "matched_keywords": list(matched),
        "preview_hash": preview.get("preview_hash"),
    }
