"""Orchestrator HTTP API

启动方法:
    python -m uvicorn orchestrator.api:app --host 0.0.0.0 --port 8080

端点:
    GET  /health
    POST /run                 提交完整的 orchestrator 任务
    GET  /stats               当前队列和投递统计
    GET  /jobs/recent         最近完成的任务
    GET  /queue/pending       待处理任务
    POST /candidate           候选人管理
    GET  /candidate/{id}      获取候选人
    GET  /metrics             Prometheus 指标
"""
import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .applier_client import ApplierClient
from .config import CONFIG, CandidateProfile, CandidateStore, set_config, get_config
from .matcher_client import MatcherClient, extract_match_score
from .queue import make_queue, ApplyJob
from . import metrics, webhooks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Orchestrator API starting...")
    yield
    logger.info("Orchestrator API shutting down...")


app = FastAPI(
    title="ai-resume-autoapply",
    description="Resume-Matcher + auto_job 整合层 HTTP API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    resume_path: str
    jd_file_path: Optional[str] = None
    jd_list: Optional[list] = Field(default=None, description="[{company, title, jd_text}]")
    candidate_name: Optional[str] = None
    candidate_title: Optional[str] = None
    candidate_years: Optional[int] = None
    max_jobs: int = 10
    min_score: Optional[float] = None

    # Forward-compatible: UI may send a scrape payload instead of jd_list/jd_file_path
    scrape: Optional[dict] = Field(default=None, description="前端搜索抓取参数")


class RunResponse(BaseModel):
    status: str
    run_id: str
    queued: int = 0
    skipped: int = 0
    failed: int = 0
    avg_ats_score: float = 0.0


class CandidateRequest(BaseModel):
    name: str = Field(max_length=200)
    title: str = ""
    years: int = 0
    resume_path: str = ""
    skills: list = Field(default_factory=list)
    contact: dict = Field(default_factory=dict)


class CandidateResponse(BaseModel):
    id: str
    name: str
    title: str
    years: int
    resume_path: str


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": app.version,
        "min_match_score": CONFIG.matcher.min_match_score,
        "max_per_hour": CONFIG.antiban.max_apply_per_hour,
        "max_per_day": CONFIG.antiban.max_apply_per_day,
    }


@app.post("/run", response_model=RunResponse)
async def run_orchestrator(req: RunRequest, background_tasks: BackgroundTasks):
    run_id = uuid.uuid4().hex[:12]

    if req.min_score is not None:
        CONFIG.matcher.min_match_score = req.min_score

    jd_list = []
    if req.jd_list:
        jd_list = req.jd_list
    elif req.jd_file_path:
        path = Path(req.jd_file_path)
        if not path.exists():
            raise HTTPException(404, f"JD file not found: {req.jd_file_path}")
        jd_list = json.loads(path.read_text(encoding="utf-8"))

    if not jd_list:
        # 兼容前端直接发送的 scrape 字段
        if req.scrape:
            # 延迟导入避免循环
            from orchestrator.scraper import quick_scrape
            query = req.scrape.get("query") or ""
            city = req.scrape.get("city") or ""
            max_jobs = int(req.scrape.get("max_jobs") or req.max_jobs)
            if query:
                jd_list = quick_scrape(query, city, max_jobs)
        if not jd_list:
            raise HTTPException(400, "No JD list provided (use jd_file_path, jd_list, or scrape)")

    candidate = {
        "name": req.candidate_name or "求职者",
        "title": req.candidate_title or "",
        "years": req.candidate_years or 0,
    }

    background_tasks.add_task(
        _run_in_background,
        run_id,
        req.resume_path,
        jd_list,
        candidate,
        req.max_jobs,
    )

    metrics.INFLIGHT_RUNS.inc()
    return RunResponse(status="started", run_id=run_id)


@app.get("/stats")
async def stats():
    queue = make_queue()
    return {
        "queue": queue.get_stats(),
        "config": {
            "min_match_score": CONFIG.matcher.min_match_score,
            "max_per_hour": CONFIG.antiban.max_apply_per_hour,
            "max_per_day": CONFIG.antiban.max_apply_per_day,
        },
    }


@app.get("/jobs/recent")
async def recent_jobs(limit: int = 20):
    try:
        queue = make_queue()
        return {"jobs": queue.get_recent_completed(limit=limit)}
    except Exception as e:
        logger.warning(f"/jobs/recent degraded: {e}")
        return {"jobs": []}


@app.get("/queue/pending")
async def queue_pending(limit: int = 50):
    queue = make_queue()
    if hasattr(queue, "redis"):
        items = queue.redis.lrange("ai-resume:jobs:pending", 0, limit - 1)
        return {"jobs": [json.loads(item) for item in items]}
    return {"jobs": []}


@app.post("/candidate", response_model=CandidateResponse)
async def create_candidate(req: CandidateRequest):
    store = CandidateStore()
    profile = CandidateProfile(
        id=uuid.uuid4().hex[:12],
        name=req.name,
        title=req.title,
        years=req.years,
        resume_path=req.resume_path,
        skills=req.skills,
        contact=req.contact,
    )
    store.save(profile)
    metrics.CANDIDATES_TOTAL.inc()
    return CandidateResponse(
        id=profile.id,
        name=profile.name,
        title=profile.title,
        years=profile.years,
        resume_path=profile.resume_path,
    )


@app.get("/candidate/{cid}")
async def get_candidate(cid: str):
    store = CandidateStore()
    profile = store.get(cid)
    if not profile:
        raise HTTPException(404, f"Candidate {cid} not found")
    return profile


@app.get("/candidates")
async def list_candidates():
    store = CandidateStore()
    return {"candidates": store.list_all()}


@app.post("/resume/upload")
async def upload_resume(file: UploadFile = File(...)):
    save_dir = Path("./uploads")
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    save_path.write_bytes(await file.read())
    return {"path": str(save_path), "filename": file.filename, "size": len(save_path.read_bytes())}


@app.get("/metrics")
async def prom_metrics():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(metrics.render())


async def _run_in_background(run_id, resume_path, jd_list, candidate, max_jobs):
    started = time.time()
    logger.info(f"[{run_id}] Starting: {len(jd_list)} JDs")
    queued = 0
    skipped = 0
    failed = 0
    scores = []

    async with MatcherClient() as matcher:
        applier = ApplierClient()
        try:
            upload = await matcher.upload_resume(resume_path)
            resume_id = upload["id"]
        except Exception as e:
            logger.error(f"[{run_id}] Resume upload failed: {e}")
            webhooks.notify_error(f"[{run_id}] Resume upload failed: {e}")
            metrics.RUNS_TOTAL.labels(status="failed").inc()
            return

        for i, job_meta in enumerate(jd_list[:max_jobs], 1):
            try:
                jd_upload = await matcher.upload_job_description(
                    job_meta.get("jd_text", ""),
                    resume_id=resume_id,
                    jd_name=f"{job_meta.get('company', 'unknown')}-{job_meta.get('title', '')}",
                )
                job_id = jd_upload["job_id"]

                preview = await matcher.improve_preview(resume_id, job_id)
                score = extract_match_score(preview)
                scores.append(score["overall_score"])

                if score["overall_score"] < CONFIG.matcher.min_match_score:
                    logger.info(f"[{run_id}] {i}/{max_jobs} skipped (score {score['overall_score']:.1f})")
                    skipped += 1
                    metrics.JOBS_PROCESSED.labels(result="skipped").inc()
                    continue

                preview_hash = score.get("preview_hash", "")
                if preview_hash:
                    try:
                        await matcher.improve_confirm(resume_id, job_id, preview_hash)
                    except Exception:
                        pass

                cover_letter = ""
                try:
                    tailored_id = score.get("tailored_resume_id", resume_id)
                    cover_letter = await matcher.generate_cover_letter(tailored_id)
                except Exception as e:
                    logger.warning(f"[{run_id}] Cover letter failed: {e}")

                record = applier.apply(
                    job_id=job_id,
                    job_title=job_meta.get("title", ""),
                    company=job_meta.get("company", ""),
                    jd_text=job_meta.get("jd_text", ""),
                    cover_letter=cover_letter,
                    candidate_name=candidate["name"],
                    candidate_title=candidate["title"],
                    years_experience=candidate["years"],
                    matched_skills=score.get("matched_keywords", []),
                    missing_skills=score.get("missing_keywords", []),
                    ats_score=score["overall_score"],
                )
                if record.success:
                    queued += 1
                    metrics.JOBS_PROCESSED.labels(result="queued").inc()
                    metrics.ATS_SCORE.observe(score["overall_score"])
                    logger.info(f"[{run_id}] {i}/{max_jobs} queued ({job_meta.get('company')})")
                else:
                    failed += 1
                    metrics.JOBS_PROCESSED.labels(result="failed").inc()

            except Exception as e:
                logger.exception(f"[{run_id}] {i}/{max_jobs} failed: {e}")
                failed += 1
                metrics.JOBS_PROCESSED.labels(result="error").inc()

    duration = time.time() - started
    avg_score = sum(scores) / max(1, len(scores))
    metrics.RUN_DURATION.observe(duration)
    metrics.RUNS_TOTAL.labels(status="completed").inc()
    metrics.INFLIGHT_RUNS.dec()

    summary = {
        "run_id": run_id,
        "queued": queued,
        "skipped": skipped,
        "failed": failed,
        "avg_score": avg_score,
        "duration": duration,
    }
    logger.info(f"[{run_id}] Done: {summary}")
    webhooks.notify_run_complete(summary)


@app.get("/boss/accounts")
async def boss_accounts():
  accounts = []
  try:
    from finding_jobs_v2 import load_boss_accounts
    accounts = load_boss_accounts() or []
  except Exception:
    accounts = [{"label": "默认账号", "session_dir": "/tmp/boss_chrome_session"}]
  sanitized = []
  for idx, acc in enumerate(accounts):
    sanitized.append({
      "label": acc.get("label") or ("账号 " + str(idx + 1)),
      "session_dir": acc.get("session_dir") or ("/tmp/boss_chrome_session_" + str(idx))
    })
  return {"accounts": sanitized}


@app.post("/boss/apply")
async def boss_apply(req: dict, background_tasks: BackgroundTasks):
  boss_job_id = (req.get("boss_job_id") or "").strip()
  jd_text = req.get("jd_text") or ""
  cover_letter = req.get("cover_letter") or ""
  resume_id = req.get("resume_id") or ""
  candidate = req.get("candidate") or {}
  max_jobs = int(req.get("max_jobs") or 1)
  run_id = uuid.uuid4().hex[:12]
  if not boss_job_id and not jd_text:
    raise HTTPException(400, "Provide boss_job_id or jd_text")
  job = ApplyJob(
    job_id=run_id,
    boss_job_id=boss_job_id,
    company=candidate.get("company") or "未知公司",
    title=candidate.get("title") or "BOSS职位",
    jd_text=jd_text,
    cover_letter=cover_letter,
    candidate_name=candidate.get("name") or "求职者",
    candidate_title=candidate.get("title") or "",
    years_experience=int(candidate.get("years") or 0),
    resume_pdf_path=req.get("resume_path") or resume_id,
  )
  used_real = False
  try:
      auto_job_dir = Path(__file__).resolve().parent.parent.parent / "auto_job" / "auto_job_find"
      if auto_job_dir.exists():
          import sys as _sys
          if str(auto_job_dir) not in _sys.path:
              _sys.path.insert(0, str(auto_job_dir))
          from finding_jobs_v2 import open_browser_with_stealth, wait_for_login, click_chat_button, send_message_to_chat_box, load_boss_accounts
          from prompts_v2 import build_cover_letter_prompt
          account = _pick_boss_account()
          session_dir = req.get("account_session_dir") or ("/tmp/boss_chrome_session_" + str(hash(str(account))) if account else "/tmp/boss_chrome_session")
          os.makedirs(session_dir, exist_ok=True)
          base_url = "https://www.zhipin.com/web/geek/job-recommend?ka=header-job-recommend"
          target_url = f"https://www.zhipin.com/gongsi/job/{boss_job_id}.html" if boss_job_id else base_url
          driver = open_browser_with_stealth(target_url, session_dir=session_dir)
          wait_for_login(180)
          prompt = build_cover_letter_prompt(
              candidate_name=candidate.get("name") or "求职者",
              candidate_title=candidate.get("title") or "",
              years_experience=int(candidate.get("years") or 0),
              matched_skills=[candidate.get("top_skill") or "相关技术栈"],
              missing_skills=[],
              ats_score=78.0,
              job_description=jd_text or "",
          )
          sent = False
          if click_chat_button():
              send_message_to_chat_box(prompt)
              sent = True
          job.cover_letter = prompt if sent else ""
          job.status = "sent" if sent else "queued"
          used_real = True
  except Exception:
      used_real = False
  q = make_queue()
  q.push(job)
  result_label = getattr(job, "status", "queued") or "queued"
  metrics.JOBS_PROCESSED.labels(result=result_label).inc()
  metrics.INFLIGHT_RUNS.inc()
  background_tasks.add_task(_run_in_background, run_id, job.resume_pdf_path, [{"company": job.company, "title": job.title, "jd_text": jd_text}], candidate, max_jobs)
  return {"status": job.status, "run_id": run_id, "job_id": job.job_id}

@app.get("/boss/apply/{run_id}/result")
async def boss_apply_result(run_id: str):
  q = make_queue()
  job = None
  if hasattr(q, "recent"):
      jobs = q.recent(limit=50)
      job = next((j for j in jobs if j.get("job_id") == run_id), None)
  if not job:
      raise HTTPException(404, "run_id not found")
  return {
    "run_id": run_id,
    "status": job.get("status", "queued"),
    "company": job.get("company", ""),
    "title": job.get("title", ""),
    "boss_job_id": job.get("boss_job_id", ""),
    "created_at": str(job.get("created_at", "")),
  }

@app.get("/boss/jobs/{boss_job_id}")
async def boss_job_detail(boss_job_id: str):
  return {"boss_job_id": boss_job_id, "title": "", "company": "", "active": True}

@app.get("/boss/apply/recent")
async def boss_apply_recent(limit: int = 20):
  q = make_queue()
  out = []
  if hasattr(q, "recent"):
    for j in q.recent(limit=limit):
      out.append({"run_id": j.get("job_id"), "status": j.get("status"), "company": j.get("company"), "title": j.get("title"), "boss_job_id": j.get("boss_job_id", ""), "created_at": j.get("created_at")})
  return {"items": out}

@app.get("/alerts/recent")
async def alerts_recent(limit: int = 50):
    return {"alerts": metric_alerts.recent(limit=limit)}
async def _boss_apply_with_retry(payload: dict):
    import time
    from .config import CONFIG
    max_retries = getattr(CONFIG, "BOSS_APPLY_MAX_RETRIES", 3)
    backoff_base = getattr(CONFIG, "BOSS_APPLY_BACKOFF_BASE", 2.0)
    backoff_max = getattr(CONFIG, "BOSS_APPLY_BACKOFF_MAX", 60.0)
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            return await _attempt_boss_apply(payload)
        except Exception as e:
            last_err = e
            wait = min(backoff_base ** attempt, backoff_max)
            print(f"boss apply attempt {attempt} failed: {e}, retry in {wait}s")
            time.sleep(wait)
    raise last_err

async def _attempt_boss_apply(payload: dict):
    # Reuse real apply logic without retry
    boss_job_id = (payload.get("boss_job_id") or "").strip()
    jd_text = payload.get("jd_text") or ""
    candidate = payload.get("candidate") or {}
    auto_job_dir = Path(__file__).resolve().parent.parent.parent / "auto_job" / "auto_job_find"
    if not auto_job_dir.exists():
        raise RuntimeError("auto_job modules missing")
    import sys as _sys
    if str(auto_job_dir) not in _sys.path:
        _sys.path.insert(0, str(auto_job_dir))
    from finding_jobs_v2 import open_browser_with_stealth, wait_for_login, click_chat_button, send_message_to_chat_box
    from prompts_v2 import build_cover_letter_prompt
    url = "https://www.zhipin.com/web/geek/job-recommend?ka=header-job-recommend" if not boss_job_id else f"https://www.zhipin.com/gongsi/job/{boss_job_id}.html"
    open_browser_with_stealth(url)
    wait_for_login(180)
    cover = build_cover_letter_prompt(
        candidate_name=candidate.get("name") or "求职者",
        candidate_title=candidate.get("title") or "",
        years_experience=int(candidate.get("years") or 0),
        matched_skills=[candidate.get("top_skill") or "相关技术栈"],
        missing_skills=[],
        ats_score=78.0,
        job_description=jd_text or "",
    )
    sent = False
    if click_chat_button():
        send_message_to_chat_box(cover)
        sent = True
    return {"sent": sent, "cover_letter": cover if sent else ""}


def _pick_boss_account():
    from .config import CONFIG
    accounts = getattr(CONFIG, "BOSS_ACCOUNTS", [])
    if not accounts:
        return None
    strategy = getattr(CONFIG, "ACCOUNT_SELECTION", "round_robin")
    if strategy == "random":
        import random
        return random.choice(accounts)
    if strategy == "least_used":
        # placeholder: choose first for now
        return accounts[0]
    # round_robin default
    idx = getattr(_pick_boss_account, "_rr_index", 0)
    _pick_boss_account._rr_index = (idx + 1) % len(accounts)
    return accounts[idx]

@app.post("/boss/apply/batch")
async def boss_apply_batch(req: dict, background_tasks: BackgroundTasks):
  items = req.get("items") or []
  candidate = req.get("candidate") or {}
  max_jobs = int(req.get("max_jobs") or len(items))
  run_id = uuid.uuid4().hex[:12]
  q = make_queue()
  results = []
  for i, item in enumerate(items[:max_jobs]):
      job = ApplyJob(
          job_id=f"{run_id}_{i}",
          boss_job_id=(item.get("boss_job_id") or "").strip(),
          company=item.get("company") or candidate.get("company") or "未知公司",
          title=item.get("title") or candidate.get("title") or "BOSS职位",
          jd_text=item.get("jd_text") or "",
          cover_letter=item.get("cover_letter") or "",
          candidate_name=candidate.get("name") or "求职者",
          candidate_title=candidate.get("title") or "",
          years_experience=int(candidate.get("years") or 0),
          resume_pdf_path=req.get("resume_path") or "",
      )
      q.push(job)
      metrics.JOBS_PROCESSED.labels(result="queued").inc()
      results.append({"job_id": job.job_id, "company": job.company, "title": job.title})
  metrics.INFLIGHT_RUNS.inc()
  return {"status": "queued", "run_id": run_id, "count": len(results), "jobs": results}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
