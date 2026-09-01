"""Resume-Matcher HTTP 客户端

对接 Resume-Matcher 后端 FastAPI（端口 8000）。

实际端点（来自 apps/backend/app/routers/resumes.py）：
  POST /api/v1/resumes/upload
  POST /api/v1/resumes/improve/preview
  POST /api/v1/resumes/improve/confirm
  POST /api/v1/jobs/upload
  POST /api/v1/resumes/{resume_id}/generate-cover-letter
  GET  /api/v1/resumes/{resume_id}/pdf
  GET  /api/v1/health
"""
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class MatcherClient:
    """Resume-Matcher 后端 HTTP 客户端"""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        """检查后端健康状态"""
        resp = await self._client.get("/api/v1/health")
        resp.raise_for_status()
        return resp.json()

    async def upload_resume(self, file_path: str) -> dict[str, Any]:
        """上传 master 简历（PDF/DOCX/MD）

        Returns:
            {"id": "resume_xxx", "filename": "...", "is_master": true, ...}
        """
        with open(file_path, "rb") as f:
            files = {"file": (file_path.split("/")[-1], f, "application/octet-stream")}
            resp = await self._client.post("/api/v1/resumes/upload", files=files)
        resp.raise_for_status()
        return resp.json()

    async def upload_job_description(
        self,
        jd_text: str,
        resume_id: str = "",
        jd_name: str = "JD",
    ) -> dict[str, Any]:
        """上传 JD 文本到 Resume-Matcher

        实际端点 POST /api/v1/jobs/upload 接受 job_descriptions 和 resume_id
        返回 {message, job_id: [job_xxx], ...}

        Returns:
            dict with job_id
        """
        resp = await self._client.post(
            "/api/v1/jobs/upload",
            json={
                "job_descriptions": [jd_text],
                "resume_id": resume_id,
                "name": jd_name,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        job_ids = data.get("job_id", [])
        if job_ids:
            data["job_id"] = job_ids[0]
        return data

    async def improve_preview(self, resume_id: str, job_id: str) -> dict[str, Any]:
        """获取简历改写预览（含 ATS 评分）

        Returns:
            {
              "resume_id": "...",
              "improved_resume_id": "...",
              "preview_hash": "...",
              "score": {
                "keyword_match": 75.0,
                "skills_coverage": 80.0,
                "section_completeness": 100.0,
                "overall": 78.5
              },
              "matched_keywords": ["Swift", "SwiftUI"],
              "missing_keywords": ["Metal"],
              ...
            }
        """
        resp = await self._client.post(
            "/api/v1/resumes/improve/preview",
            json={"resume_id": resume_id, "job_id": job_id},
        )
        resp.raise_for_status()
        return resp.json()

    async def improve_confirm(
        self, resume_id: str, job_id: str, preview_hash: str
    ) -> dict[str, Any]:
        """确认改写，生成 tailored resume

        Returns:
            {"resume_id": "tailored_xxx", ...}
        """
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

    async def generate_cover_letter(self, resume_id: str, job_id: str | None = None) -> str:
        """生成求职信

        注意：Resume-Matcher 后端要求 resume_id 是 tailored resume（必须先 improve/confirm）。

        Returns:
            求职信正文字符串
        """
        # 实际端点：POST /api/v1/resumes/{resume_id}/generate-cover-letter
        # 它从 improvement 表查 job_id，不需要单独传
        resp = await self._client.post(f"/api/v1/resumes/{resume_id}/generate-cover-letter")
        resp.raise_for_status()
        data = resp.json()
        return data.get("content", "")

    async def get_resume_pdf(self, resume_id: str) -> bytes:
        """获取改写后的 PDF（用于 BOSS 附件投递）"""
        resp = await self._client.get(f"/api/v1/resumes/{resume_id}/pdf")
        resp.raise_for_status()
        return resp.content


def extract_match_score(preview: dict[str, Any]) -> dict[str, Any]:
    """从 improve_preview 响应中提取 ATS 评分

    兼容多种返回结构：
    - {"score": {"overall": ...}} （新）
    - {"ats_score": ...}          （旧）
    - 顶层有 keyword_match 等字段
    """
    score = preview.get("score", {})

    # 优先从 score 子对象读
    overall = score.get("overall", 0.0)
    keyword_match = score.get("keyword_match", 0.0)
    skills_coverage = score.get("skills_coverage", 0.0)
    section_completeness = score.get("section_completeness", 0.0)

    # fallback: 顶层
    if not overall:
        overall = preview.get("ats_score", preview.get("overall_score", 0.0))
    if not keyword_match:
        keyword_match = preview.get("keyword_match", 0.0)
    if not skills_coverage:
        skills_coverage = preview.get("skills_coverage", 0.0)
    if not section_completeness:
        section_completeness = preview.get("section_completeness", 0.0)

    return {
        "overall_score": float(overall),
        "keyword_match": float(keyword_match),
        "skills_coverage": float(skills_coverage),
        "section_completeness": float(section_completeness),
        "matched_keywords": preview.get("matched_keywords", []),
        "missing_keywords": preview.get("missing_keywords", []),
        "preview_hash": preview.get("preview_hash", ""),
        "tailored_resume_id": preview.get("improved_resume_id", ""),
    }
