from pathlib import Path
p = Path('/Users/bianyawen/WorkBuddy/2026-08-06-22-17-40/ai-resume-integration/ai-resume-autoapply/orchestrator/api.py')
text = p.read_text(encoding='utf-8')

old_block = '''@app.post("/boss/apply")
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
  q = make_queue()
  q.push(job)
  metrics.JOBS_PROCESSED.labels(result="queued").inc()
  metrics.INFLIGHT_RUNS.inc()
  background_tasks.add_task(_run_in_background, run_id, job.resume_pdf_path, [{"company": job.company, "title": job.title, "jd_text": jd_text}], candidate, max_jobs)
  return {"status": "queued", "run_id": run_id, "job_id": job.job_id}'''

new_block = '''@app.post("/boss/apply")
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
  status = "queued"
  try:
      auto_job_dir = Path(__file__).resolve().parent.parent.parent / "auto_job" / "auto_job_find"
      if auto_job_dir.exists():
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
          if click_chat_button():
              send_message_to_chat_box(cover)
              job.cover_letter = cover
              status = "sent"
  except Exception as e:
      status = "queued"
  q = make_queue()
  q.push(job)
  metrics.JOBS_PROCESSED.labels(result=status).inc()
  metrics.INFLIGHT_RUNS.inc()
  background_tasks.add_task(_run_in_background, run_id, job.resume_pdf_path, [{"company": job.company, "title": job.title, "jd_text": jd_text}], candidate, max_jobs)
  return {"status": status, "run_id": run_id, "job_id": job.job_id}'''

if old_block not in text:
  raise SystemExit('boss endpoint block not found')
p.write_text(text.replace(old_block, new_block), encoding='utf-8')
