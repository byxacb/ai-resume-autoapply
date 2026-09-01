"""Webhook notifications (DingTalk / Feishu / Email / Slack).

Why this matters:
- When BOSS worker applies to 100 jobs overnight, you want a morning summary
- When something breaks (login expires, JD too short), immediate alert
- When a high-match JD is found (> 85), push notification for manual review

Configuration via env vars:
    DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=...
    DINGTALK_SECRET=SEC...
    FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/...
    SLACK_WEBHOOK=https://hooks.slack.com/services/...
    EMAIL_SMTP_HOST=smtp.gmail.com
    EMAIL_SMTP_PORT=587
    EMAIL_USER=...
    EMAIL_PASS=...
    EMAIL_TO=user@example.com

Webhook signing follows each platform's official spec (HMAC-SHA256 for DingTalk, etc.)
"""
import asyncio
import hashlib
import hmac
import base64
import json
import logging
import os
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


async def _post_json(url: str, payload: Dict, timeout: float = 10.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.warning(f"Webhook POST failed ({url[:60]}): {e}")
        return False


def _dingtalk_sign(secret: str) -> tuple:
    """DingTalk HMAC-SHA256 sign.

    Returns (timestamp, sign) to append to URL.
    """
    timestamp = str(round(time.time() * 1000))
    secret_enc = secret.encode("utf-8")
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    hmac_code = hmac.new(secret_enc, string_to_sign, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return timestamp, sign


async def notify_dingtalk(text: str, title: str = "ai-resume-autoapply") -> bool:
    url = os.getenv("DINGTALK_WEBHOOK")
    if not url:
        return False
    secret = os.getenv("DINGTALK_SECRET", "")

    if secret:
        ts, sign = _dingtalk_sign(secret)
        url = f"{url}&timestamp={ts}&sign={sign}"

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"### {title}\n\n{text}",
        },
    }
    return await _post_json(url, payload)


async def notify_feishu(text: str) -> bool:
    url = os.getenv("FEISHU_WEBHOOK")
    if not url:
        return False
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": "ai-resume-autoapply"}},
            "elements": [{"tag": "markdown", "content": text}],
        },
    }
    return await _post_json(url, payload)


async def notify_slack(text: str) -> bool:
    url = os.getenv("SLACK_WEBHOOK")
    if not url:
        return False
    payload = {"text": f"[ai-resume-autoapply] {text}"}
    return await _post_json(url, payload)


async def notify_email(subject: str, body: str) -> bool:
    """Send email via SMTP. Returns True on success."""
    host = os.getenv("EMAIL_SMTP_HOST")
    if not host:
        return False

    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.getenv("EMAIL_USER", "ai-resume@example.com")
    msg["To"] = os.getenv("EMAIL_TO", "")
    msg.set_content(body)

    try:
        port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
        user = os.getenv("EMAIL_USER", "")
        password = os.getenv("EMAIL_PASS", "")

        def _send():
            with smtplib.SMTP(host, port) as server:
                server.starttls()
                if user and password:
                    server.login(user, password)
                server.send_message(msg)

        await asyncio.to_thread(_send)
        return True
    except Exception as e:
        logger.warning(f"Email send failed: {e}")
        return False


async def notify_all(text: str, title: Optional[str] = None) -> Dict[str, bool]:
    """Send to all configured webhooks."""
    results = {}
    if os.getenv("DINGTALK_WEBHOOK"):
        results["dingtalk"] = await notify_dingtalk(text, title or "ai-resume-autoapply")
    if os.getenv("FEISHU_WEBHOOK"):
        results["feishu"] = await notify_feishu(text)
    if os.getenv("SLACK_WEBHOOK"):
        results["slack"] = await notify_slack(text)
    if os.getenv("EMAIL_SMTP_HOST"):
        results["email"] = await notify_email(title or "ai-resume-autoapply", text)
    return results


# === High-level notifications ===

async def notify_run_complete(summary: Dict[str, Any]) -> None:
    text = (
        f"**Run {summary.get('run_id', '?')}** 完成了\n"
        f"- Queued: {summary.get('queued', 0)}\n"
        f"- Skipped (low score): {summary.get('skipped', 0)}\n"
        f"- Failed: {summary.get('failed', 0)}\n"
        f"- Avg ATS score: {summary.get('avg_score', 0):.1f}\n"
        f"- Duration: {summary.get('duration', 0):.0f}s"
    )
    await notify_all(text)


async def notify_high_match_job(job_meta: Dict[str, Any], ats_score: float) -> None:
    text = (
        f"**High-match job found!**\n"
        f"- Company: {job_meta.get('company', '?')}\n"
        f"- Title: {job_meta.get('title', '?')}\n"
        f"- ATS score: {ats_score:.1f}\n"
        f"- Action: queued for auto-apply"
    )
    await notify_all(text)


async def notify_error(message: str) -> None:
    text = f"**Error** 🚨\n\n{message}"
    await notify_all(text)


async def notify_rate_limit(platform: str, wait_seconds: int) -> None:
    text = (
        f"⏸️ Rate limit reached on {platform}\n"
        f"Pausing for {wait_seconds}s"
    )
    await notify_all(text, title="ai-resume-rate-limit")
