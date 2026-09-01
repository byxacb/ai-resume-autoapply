"""整合层主入口

串联流程：
  1. 上传 master 简历到 Resume-Matcher
  2. 抓 BOSS 上的 JD（或从外部导入）
  3. 对每个 JD：
     a. 上传 JD 到 Resume-Matcher
     b. 调用 improve_preview 获取 ATS 评分
     c. 评分 < 阈值 → 跳过（避免海投低匹配）
     d. 评分 ≥ 阈值 → 改写简历 + 生成求职信
     e. push 到 Redis 队列（auto_job worker 异步投递）
     f. 记录投递结果 + 风控统计

用法：
  # CLI 模式（适合测试）
  python -m orchestrator.run --resume ./resume.pdf --jd-file ./jds.json

  # 服务模式（适合生产，常驻）
  python -m orchestrator.run --server --port 8080
"""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .applier_client import ApplierClient
from .config import CONFIG
from .matcher_client import MatcherClient, extract_match_score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def process_one_job(matcher, applier, resume_id, job_id, job_meta, candidate_info):
    """处理一个 JD：评分 → 改写 → 入队"""
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
        f"  ATS: {overall:.1f} "
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
    cover_letter = ""
    try:
        cover_letter = await matcher.generate_cover_letter(resume_id, job_id)
    except Exception as e:
        logger.error(f"Cover letter generation failed: {e}")

    # Step 5: push 到 Redis 队列（worker 异步处理）
    record = applier.apply(
        job_id=job_id,
        job_title=title,
        company=company,
        jd_text=job_meta.get("jd_text", ""),
        cover_letter=cover_letter,
        candidate_name=candidate_info.get("name", ""),
        candidate_title=candidate_info.get("title", ""),
        years_experience=candidate_info.get("years", 0),
        matched_skills=scores.get("matched_keywords", []),
        missing_skills=scores.get("missing_keywords", []),
        ats_score=overall,
    )

    return {
        "job_id": job_id,
        "status": "queued" if record.success else "queue_failed",
        "ats_score": overall,
        "scores": scores,
        "error": record.error,
    }


async def main_async(args):
    logger.info("=" * 60)
    logger.info("ai-resume-autoapply orchestrator")
    logger.info(f"Resume: {args.resume}")
    logger.info(f"Min ATS score: {CONFIG.matcher.min_match_score}")
    logger.info(f"Redis URL: {args.redis_url or 'in-memory'}")
    logger.info("=" * 60)

    # 健康检查
    async with MatcherClient() as matcher:
        try:
            health = await matcher.health()
            logger.info(f"Resume-Matcher health: {health}")
        except Exception as e:
            logger.error(f"Resume-Matcher backend unreachable: {e}")
            logger.error("Start it with:")
            logger.error("  cd Resume-Matcher/apps/backend")
            logger.error("  uv run uvicorn app.main:app --reload --port 8000")
            sys.exit(1)

        # 上传 master 简历
        upload = await matcher.upload_resume(args.resume)
        resume_id = upload["id"]
        logger.info(f"Resume uploaded: id={resume_id}")

        # 候选人信息（从参数或文件读）
        candidate_info = load_candidate_info(args)

        # 准备 RPA 客户端
        applier = ApplierClient(redis_url=args.redis_url)
        logger.info(f"Anti-ban: {applier.get_stats_summary()}")

        # 抓 JD 列表
        jd_list = await fetch_jd_list(args)
        logger.info(f"Found {len(jd_list)} JDs to process")

        # 处理每个 JD
        results = []
        for i, job_meta in enumerate(jd_list[: args.max], 1):
            logger.info(f"[{i}/{min(len(jd_list), args.max)}] {job_meta.get('company')}/{job_meta.get('title')}")
            jd_text = job_meta.get("jd_text", "")
            if not jd_text:
                logger.warning("  No JD text, skipping")
                continue

            jd_upload = await matcher.upload_job_description(jd_text)
            job_id = jd_upload["id"]
            result = await process_one_job(
                matcher, applier, resume_id, job_id, job_meta, candidate_info
            )
            results.append(result)

        # 汇总
        logger.info("=" * 60)
        applied = sum(1 for r in results if r["status"] == "queued")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        failed = sum(1 for r in results if r["status"] == "queue_failed")
        avg_score = (
            sum(r["ats_score"] for r in results if "ats_score" in r)
            / max(1, len([r for r in results if "ats_score" in r]))
        )
        logger.info(f"📊 Summary:")
        logger.info(f"  Queued: {applied}")
        logger.info(f"  Skipped (low score): {skipped}")
        logger.info(f"  Failed: {failed}")
        logger.info(f"  Avg ATS score: {avg_score:.1f}")
        logger.info(f"  Final: {applier.get_stats_summary()}")

        # 保存结果
        if args.output:
            Path(args.output).write_text(
                json.dumps(results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(f"Results saved to {args.output}")


def load_candidate_info(args) -> dict:
    """从命令行或文件读候选人信息"""
    if args.candidate_info:
        path = Path(args.candidate_info)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))

    return {
        "name": args.candidate_name or "求职者",
        "title": args.candidate_title or "",
        "years": args.candidate_years or 0,
    }


async def fetch_jd_list(args) -> list:
    """抓取 JD 列表

    优先级：
    1. --jd-file（JSON 文件）
    2. --boss-url（从 BOSS 抓，需 worker 端提供）
    3. 空列表（提示用户怎么用）
    """
    if args.jd_file:
        path = Path(args.jd_file)
        if not path.exists():
            logger.error(f"JD file not found: {path}")
            return []
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    logger.warning("No --jd-file provided.")
    logger.warning("See docs/INTEGRATION_PLAN.md for BOSS scraper integration.")
    return []


def main():
    parser = argparse.ArgumentParser(description="AI 简历优化 + 自动投递")
    parser.add_argument("--resume", required=True, help="Master 简历 PDF/DOCX 路径")
    parser.add_argument("--jd-file", help="JD JSON 文件路径")
    parser.add_argument("--max", type=int, default=10, help="最多处理 JD 数")
    parser.add_argument("--redis-url", help="Redis URL（如 redis://localhost:6379/0）")
    parser.add_argument("--output", help="结果输出 JSON 路径")
    parser.add_argument("--candidate-info", help="候选人信息 JSON 文件")
    parser.add_argument("--candidate-name", help="候选人姓名（覆盖文件）")
    parser.add_argument("--candidate-title", help="目标岗位（覆盖文件）")
    parser.add_argument("--candidate-years", type=int, help="工作年限（覆盖文件）")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
