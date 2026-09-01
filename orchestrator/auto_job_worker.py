"""auto_job Worker - 真实 Selenium 投递 worker

持续从 Redis 队列里 pop 任务，通过 undetected-chromedriver
调用 finding_jobs_v2.py / write_response_v2.py 完成投递。

启动方法：
    cd auto_job/auto_job_find
    python ../../ai-resume-autoapply/orchestrator/auto_job_worker.py

或者独立运行：
    cd ai-resume-autoapply/orchestrator
    python auto_job_worker.py
"""
import logging
import os
import signal
import sys
import time
from pathlib import Path

# 让 worker 能找到 auto_job 包
AUTO_JOB_DIR = Path(__file__).resolve().parent.parent.parent / "auto_job" / "auto_job_find"
sys.path.insert(0, str(AUTO_JOB_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] worker: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("auto_job_worker")

# 延迟导入 auto_job 模块
try:
    from finding_jobs_v2 import (
        open_browser_with_stealth,
        wait_for_login,
        get_job_description_by_xpath_safe,
        click_chat_button,
        send_message_to_chat_box,
        human_like_delay,
        get_driver,
        _driver,
    )
    from write_response_v2 import call_llm, extract_company_name
    from rate_limiter import BossRateLimiter
    AUTO_JOB_OK = True
except ImportError as e:
    logger.error(f"Failed to import auto_job modules: {e}")
    AUTO_JOB_OK = False


# 优雅退出
_running = True


def _signal_handler(signum, frame):
    global _running
    logger.info(f"Received signal {signum}, shutting down...")
    _running = False


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def process_one_job(job) -> dict:
    """处理一个 Redis 队列里的任务

    Args:
        job: ApplyJob 实例

    Returns:
        {"success": bool, "error": str}
    """
    driver = get_driver()
    if driver is None:
        return {"success": False, "error": "Browser not initialized"}

    try:
        logger.info(f"Processing job {job.job_id}: {job.company}/{job.title}")

        # 1. 抓 JD（如果 job 里没有 JD 文本）
        jd_text = job.jd_text or ""
        if not jd_text:
            # 从 BOSS 当前页面抓
            jd_text = get_job_description_by_xpath_safe(1) or ""
            if not jd_text:
                return {"success": False, "error": "Could not extract JD"}

        # 2. 点击"立即沟通"
        if not click_chat_button():
            return {"success": False, "error": "Chat button not clickable (already chatted?)"}

        human_like_delay(1.5, 3.0)

        # 3. 生成/使用求职信
        cover_letter = job.cover_letter
        if not cover_letter:
            # 实时生成
            from prompts_v2 import build_cover_letter_prompt
            prompt = build_cover_letter_prompt(
                candidate_name=job.candidate_name,
                candidate_title=job.candidate_title,
                years_experience=job.years_experience,
                matched_skills=job.matched_skills,
                missing_skills=job.missing_skills,
                ats_score=job.ats_score,
                job_description=jd_text,
            )
            cover_letter = call_llm(prompt)

        if not cover_letter:
            return {"success": False, "error": "Cover letter generation failed"}

        # 4. 发送
        if not send_message_to_chat_box(cover_letter):
            return {"success": False, "error": "Send failed"}

        # 5. 返回列表
        driver.back()
        human_like_delay(2.0, 4.0)

        logger.info(f"Successfully sent job {job.job_id}")
        return {"success": True, "error": ""}

    except Exception as e:
        logger.exception(f"Error processing job {job.job_id}: {e}")
        return {"success": False, "error": str(e)}


def main_loop():
    """主循环：持续从 Redis 队列取任务"""
    if not AUTO_JOB_OK:
        logger.error("auto_job modules not available. Check sys.path.")
        sys.exit(1)

    # 延迟导入 queue（避免循环依赖）
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from queue import make_queue

    queue = make_queue()
    limiter = BossRateLimiter(max_per_hour=20, max_per_company=3)

    # 启动浏览器（一次性）
    boss_url = os.getenv(
        "BOSS_URL",
        "https://www.zhipin.com/web/geek/job-recommend?ka=header-job-recommend"
    )

    logger.info(f"Starting browser at {boss_url}...")
    driver = open_browser_with_stealth(boss_url)

    logger.info("Please scan WeChat QR to login (max 120s)...")
    try:
        wait_for_login(timeout_seconds=120)
        logger.info("Login successful!")
    except Exception as e:
        logger.error(f"Login failed: {e}")
        sys.exit(1)

    logger.info("Worker started, waiting for jobs...")
    processed = 0

    while _running:
        try:
            job = queue.pop(timeout=5)
            if not job:
                continue

            # 风控检查
            if not limiter.can_apply(job.company):
                logger.warning(f"Rate limit: skip {job.company}")
                # 不标记完成，重新放回去等下次
                time.sleep(30)
                continue

            # 处理
            result = process_one_job(job)

            if result["success"]:
                limiter.record(job.company)
                queue.complete(job)
                processed += 1
                logger.info(f"Stats: {processed} processed this session, queue: {queue.get_stats()}")
                # 风控间隔
                limiter.wait()
            else:
                queue.fail(job, result["error"])
                # 失败后等长一点，避免疯狂重试
                time.sleep(60)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            break
        except Exception as e:
            logger.exception(f"Main loop error: {e}")
            time.sleep(10)

    logger.info(f"Worker stopped. Processed {processed} jobs this session.")


if __name__ == "__main__":
    main_loop()
