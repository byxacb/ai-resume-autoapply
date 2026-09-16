# BOSS Apply Research

## Current Status
- Added POST /boss/apply with real BOSS attempt via auto_job modules.
- Added GET /boss/apply/{run_id}/result.
- Added GET /boss/apply/recent list endpoint.
- Frontend: boss-apply-form-v2 with candidate select and polling toast.
- Websocket logs + alerts/recent + chart.js metrics shipped.

## Known Limitations
- Real send requires undetected chromedriver + BOSS login scan.
- GitHub push blocked by network 502 on github.com:443.

## auto_job modules
- auto_job/auto_job_find/finding_jobs_v2.py
- auto_job/auto_job_find/write_response_v2.py
- auto_job/auto_job_find/prompts_v2.py
- auto_job/auto_job_find/rate_limiter.py

## Next Steps
- Finish Playwright E2E BAT screenshots.
- Add retry queue backoff and apply status webhooks.
- Multi-account load balancing for BOSS.
