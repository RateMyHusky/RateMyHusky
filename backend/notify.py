"""Team email through Resend: one sender; feedback goes to the team inbox, the review digest to its own."""

import os

import requests as http_requests

TEAM_EMAIL = "feedback@ratemyhusky.com"
DIGEST_EMAIL = "ratings@ratemyhusky.com"


def send_team_email(subject, text, reply_to=None, to=None, html=None):
    """True when Resend accepted the email. Never raises; logs why it didn't send."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        print("[notify] RESEND_API_KEY not configured")
        return False
    payload = {"from": f"RateMyHusky <{TEAM_EMAIL}>", "to": [to or TEAM_EMAIL], "subject": subject, "text": text}
    if html:
        payload["html"] = html
    if reply_to:
        payload["reply_to"] = reply_to
    try:
        resp = http_requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
    except Exception as e:
        print(f"[notify] Resend request error: {type(e).__name__}")
        return False
    if not resp.ok:
        print(f"[notify] Resend error {resp.status_code}")
    return bool(resp.ok)


def resend_usage():
    """{"daily": {"used", "limit"}, "monthly": {...}} from Resend, or None (logged) when it can't be read."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        print("[notify] RESEND_API_KEY not configured, usage unavailable")
        return None
    try:
        resp = http_requests.get(
            "https://api.resend.com/usage",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
    except Exception as e:
        print(f"[notify] Resend usage request error: {type(e).__name__}")
        return None
    if not resp.ok:
        print(f"[notify] Resend usage error {resp.status_code}")
        return None
    try:
        emails = resp.json()["emails"]
        return {k: {"used": int(emails[k]["used"]), "limit": emails[k].get("limit")} for k in ("daily", "monthly")}
    except Exception:
        print("[notify] Resend usage reply unreadable")
        return None
