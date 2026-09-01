"""整合层主入口

串联流程：
  1. 上传 master 简历到 Resume-Matcher
  2. 抓 BOSS 上的 JD（或从外部导入）
  3. 对每个 JD：
     a. 上传 JD 到 Resume-Matcher
     b. 调用 improve_preview 获取 ATS 评分
     c. 评分 < 阈值 → 跳过（避免海投低匹配）
     d. 评分 ≥ 阈值 → 改写简历 + 生成求职信
     e. 调用 auto_job RPA 自动打招呼
     f. 记录投递结果 + 风控统计

用法：
  python -m orchestrator.run --resume ./resume.pdf --query "iOS 深圳" --max 10
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .applier_client import ApplierClient
from .config import CONFIG
from .matcher_client import MatcherClient, extract_match_score

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def process_one_job(
    matcher: MatcherClient,
    applier: ApplierClient,
    resume_id: str,
    job_id: str,
    job_meta: dict,
) -> dict:
    """处理一个 JD：评分 → 改写 → 投递"""
    company = job_meta.get("company", "未知公司")
    title = job_meta.get("title", "未知职位")

    logger.info(f"Processing {company}/{title} (job_id={job_id})")

    # Step 1: 评分
    try:
        preview = await matcher.improve_preview(resume_id, job_id)
        scores = extract_match_score(preview)
    except Exception as e:
        logger.error(f"Improve preview failed for {job_id}: {e}")
        return {"job_id": job_id, "status": "error", "error": str(e)}

    overall = scores["overall_score"]
    logger.info(
        f"  ATS score: {overall:.1f} "
        f"(kw={scores['keyword_match']:.1f}, "
        f"skills={scores['skills_coverage']:.1f}, "
        f"sec={scores['section_completeness']:.1f})"
    )

    # Step 2: 评分过滤
    if overall < CONFIG.matcher.min_match_score:
        logger.info(f"  ⏭️ Skipped: score {overall:.1f} < {CONFIG.matcher.min_match_score}")
        return {
            "job_id": job_id,
            "status": "skipped",
            "reason": f"low_match_score_{overall:.1f}",
            "scores": scores,
        }

    # Step 3: 确认改写
    try:
        preview_hash = scores.get("preview_hash")
        if preview_hash:
            await matcher.improve_confirm(resume_id, job_id, preview_hash)
    except Exception as e:
        logger.warning(f"Improve confirm failed: {e}")

    # Step 4: 生成求职信
    try:
        cover_letter = await matcher.generate_cover_letter(resume_id, job_id)
    except Exception as e:
        logger.error(f"Cover letter generation failed: {e}")
        cover_letter = ""

    # Step 5: 投递
    record = applier.apply(
        job_id=job_id,
        job_title=title,
        company=company,
        jd_text=job_meta.get("jd_text", ""),
        cover_letter=cover_letter,
    )
    record.ats_score = overall
    applier.wait_for_rate_limit()

    return {
        "job_id": job_id,
        "status": "applied" if record.success else "failed",
        "ats_score": overall,
        "scores": scores,
        "error": record.error,
    }


async def main_async(args: argparse.Namespace) -> None:
    """异步主流程"""
    logger.info("=" * 60)
    logger.info("ai-resume-autoapply orchestrator")
    logger.info(f"Resume: {args.resume}")
    logger.info(f"Query: {args.query}")
    logger.info(f"Min ATS score: {CONFIG.matcher.min_match_score}")
    logger.info("=" * 60)

    # 0. 健康检查
    async with MatcherClient() as matcher:
        try:
            health = await matcher.health()
            logger.info(f"Resume-Matcher health: {health}")
        except Exception as e:
            logger.error(f"Resume-Matcher backend not reachable: {e}")
            logger.error("Please start it with: cd Resume-Matcher/apps/backend && uv run uvicorn app.main:app --reload --port 8000")
            sys.exit(1)

        # 1. 上传简历
        upload = await matcher.upload_resume(args.resume)
        resume_id = upload["id"]
        logger.info(f"Resume uploaded: id={resume_id}")

        # 2. 抓 JD 列表
        # TODO: 接入实际的 BOSS 抓取（来自 auto_job 的 finding_jobs.py）
        # 当前简化版：从命令行或文件读 JD 列表
        jd_list = await fetch_jd_list(args)
        logger.info(f"Found {len(jd_list)} JDs to process")

        # 3. 准备 RPA
        applier = ApplierClient()
        logger.info(f"Anti-ban config: {applier.get_stats_summary()}")

        # 4. 处理每个 JD
        results = []
        for i, job_meta in enumerate(jd_list[: args.max], 1):
            logger.info(f"[{i}/{min(len(jd_list), args.max)}] {job_meta.get('company')}/{job_meta.get('title')}")

            # 上传 JD
            jd_text = job_meta.get("jd_text", "")
            if not jd_text:
                logger.warning(f"  No JD text, skipping")
                continue

            jd_upload = await matcher.upload_job_description(jd_text)
            job_id = jd_upload["id"]

            # 处理
            result = await process_one_job(matcher, applier, resume_id, job_id, job_meta)
            results.append(result)

        # 5. 汇总
        logger.info("=" * 60)
        logger.info("Summary:")
        applied = sum(1 for r in results if r["status"] == "applied")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        failed = sum(1 for r in results if r["status"] == "failed")
        logger.info(f"  Applied: {applied}")
        logger.info(f"  Skipped (low score): {skipped}")
        logger.info(f"  Failed: {failed}")
        logger.info(f"  Final rate-limit stats: {applier.get_stats_summary()}")


async def fetch_jd_list(args: argparse.Namespace) -> list[dict]:
    """抓取 JD 列表

    当前是占位实现。生产环境应该：
    1. 调用 auto_job 的 finding_jobs.get_job_description_by_index()
    2. 或者从用户提供的 JD 文件读
    3. 或者从 BOSS API 拉
    """
    if args.jd_file:
        # 从文件读 JD
        path = Path(args.jd_file)
        if not path.exists():
            logger.error(f"JD file not found: {path}")
            return []
        # 假设文件是 JSON list
        import json
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    logger.warning(
        "No --jd-file provided. Using placeholder. "
        "See docs/INTEGRATION_PLAN.md for the BOSS scraper integration."
    )
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 简历优化 + 自动投递")
    parser.add_argument("--resume", required=True, help="Master 简历 PDF/DOCX 路径")
    parser.add_argument("--query", default="iOS 深圳", help="BOSS 搜索关键词")
    parser.add_argument("--max", type=int, default=10, help="最多处理 JD 数")
    parser.add_argument("--jd-file", help="JD JSON 文件路径（替代 BOSS 抓取）")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
