import os, sys, argparse
import requests as http_requests

import notify
from rag.chat_throttle import daily_budget, projected_daily_usage, _today_ok_count


TIERS = (50, 80, 100)
TOKEN_CEILING_PER_KEY = 200_000
ALERT_EMAIL = "usage@ratemyhusky.com"


def crossed_tiers(count, budget):
    if budget <= 0:
        return []
    pct = count / budget * 100
    return [t for t in TIERS if pct >= t]


def build_summary(query_fn, query_one_fn, num_keys):
    budget = daily_budget(num_keys)
    count = _today_ok_count(query_one_fn)

    tok_row = query_one_fn(
        "SELECT coalesce(sum(tokens_used), 0) AS t FROM ask_log "
        "WHERE date_trunc('day', created_at) = current_date")
    tokens = int((tok_row or {}).get("t", 0) or 0)
    token_ceiling = TOKEN_CEILING_PER_KEY * max(num_keys, 1)
    token_pct = round(tokens / token_ceiling * 100, 1) if token_ceiling else 0.0

    status_rows = query_fn(
        "SELECT result_status, count(*) AS c FROM ask_log "
        "WHERE date_trunc('day', created_at) = current_date "
        "GROUP BY result_status ORDER BY c DESC")
    status_breakdown = {r["result_status"]: int(r["c"]) for r in (status_rows or [])}

    top_rows = query_fn(
        "SELECT session_token, count(*) AS c FROM ask_log "
        "WHERE date_trunc('day', created_at) = current_date "
        "AND mode = 'question' AND result_status = 'ok' "
        "GROUP BY session_token ORDER BY c DESC LIMIT 5")
    top_users = [(r["session_token"], int(r["c"])) for r in (top_rows or [])]

    return {
        "count": count,
        "budget": budget,
        "remaining": max(budget - count, 0),
        "tokens": tokens,
        "token_ceiling": token_ceiling,
        "token_pct": token_pct,
        "status_breakdown": status_breakdown,
        "top_users": top_users,
        "projection": projected_daily_usage(query_one_fn),
    }


def render_email(tier, s):
    subject = (f"[RateMyHusky] Usage at {tier}% — "
               f"{s['count']}/{s['budget']} questions today")
    lines = [
        f"Daily question usage crossed {tier}%.",
        "",
        "Budget & remaining",
        f"  Answered today:  {s['count']}",
        f"  Daily budget:    {s['budget']}",
        f"  Remaining:       {s['remaining']}",
        "",
        "Token usage",
        f"  Tokens today:    {s['tokens']:,}",
        f"  Token ceiling:   {s['token_ceiling']:,}",
        f"  Token %:         {s['token_pct']}%",
        "",
        "Status breakdown (today)",
    ]
    if s["status_breakdown"]:
        for status, c in s["status_breakdown"].items():
            lines.append(f"  {status:<18} {c}")
    else:
        lines.append("  (none)")
    lines += [
        "",
        f"Projected end-of-day answered questions: {s['projection']}",
        "",
        "Top users today (session_token: questions)",
    ]
    if s["top_users"]:
        for tok, c in s["top_users"]:
            lines.append(f"  {tok}: {c}")
    else:
        lines.append("  (none)")
    return subject, "\n".join(lines)


def claim_tier(write_fn, tier):
    rowcount = write_fn(
        "INSERT INTO usage_alerts (alert_date, tier) "
        "VALUES (current_date, %s) ON CONFLICT (alert_date, tier) DO NOTHING",
        (tier,))
    return bool(rowcount)


def send_email(subject, text, send_fn=None):
    if send_fn is None:
        api_key = os.getenv("RESEND_API_KEY")
        if not api_key:
            print("[usage_alert] RESEND_API_KEY not configured")
            return False

        def send_fn(payload):
            resp = http_requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json=payload, timeout=10)
            if not resp.ok:
                print(f"[usage_alert] Resend error {resp.status_code}: {resp.text}")
                return False
            return True

    payload = {
        "from": f"RateMyHusky Usage <{ALERT_EMAIL}>",
        "to": [ALERT_EMAIL],
        "subject": subject,
        "text": text,
    }
    return send_fn(payload)


def maybe_alert(query_fn, query_one_fn, write_fn, num_keys, send_fn=None):
    try:
        budget = daily_budget(num_keys)
        count = _today_ok_count(query_one_fn)
        tiers = crossed_tiers(count, budget)
        if not tiers:
            return []
        summary = None
        emailed = []
        for tier in tiers:
            if not claim_tier(write_fn, tier):
                continue
            if summary is None:
                summary = build_summary(query_fn, query_one_fn, num_keys)
            subject, text = render_email(tier, summary)
            if send_email(subject, text, send_fn=send_fn):
                try:
                    write_fn(notify.RECORD_SEND)
                except Exception as e:
                    # Best-effort: the email already went out, so the tier still counts as emailed.
                    print(f"[usage_alert] send not recorded: {type(e).__name__}")
            emailed.append(tier)
        return emailed
    except Exception as e:
        print(f"[usage_alert] maybe_alert error: {e}")
        return []


def selftest():
    fails = []
    def check(label, cond):
        if not cond: fails.append(label)
        print(("PASS" if cond else "FAIL") + ": " + label)

    # --- crossed_tiers (budget = 240 for 3 keys) ---
    check("none below 50%", crossed_tiers(100, 240) == [])           # 41%
    check("exactly 50%", crossed_tiers(120, 240) == [50])            # 50%
    check("83% -> 50+80", crossed_tiers(200, 240) == [50, 80])       # 83%
    check("100% -> all", crossed_tiers(240, 240) == [50, 80, 100])
    check("over 100% -> all", crossed_tiers(999, 240) == [50, 80, 100])
    check("zero budget guard", crossed_tiers(5, 0) == [])

    # --- build_summary ---
    def q_one(sql, params=None):
        if "sum(tokens_used)" in sql:   return {"t": 50000}
        if "result_status = 'ok'" in sql and "count(*)" in sql and "GROUP" not in sql:
            return {"c": 200}
        return {"c": 200}
    def q(sql, params=None):
        if "GROUP BY result_status" in sql:
            return [{"result_status": "ok", "c": 200},
                    {"result_status": "rate_limited", "c": 12},
                    {"result_status": "off_topic", "c": 3}]
        if "GROUP BY session_token" in sql:
            return [{"session_token": "user-a", "c": 120},
                    {"session_token": "user-b", "c": 80}]
        return []
    summary = build_summary(q, q_one, num_keys=3)
    check("summary count", summary["count"] == 200)
    check("summary budget", summary["budget"] == 240)
    check("summary remaining", summary["remaining"] == 40)
    check("summary tokens", summary["tokens"] == 50000)
    check("summary token_pct", 0 < summary["token_pct"] < 100)
    check("summary status breakdown", summary["status_breakdown"]["rate_limited"] == 12)
    check("summary top users", summary["top_users"][0] == ("user-a", 120))
    check("summary projection present", "projection" in summary)

    # --- render_email ---
    subj, text = render_email(80, summary)
    check("subject has tier", "80%" in subj)
    check("subject has count/budget", "200/240" in subj or "200 / 240" in subj)
    check("body has remaining", "40" in text)
    check("body has tokens", "50000" in text or "50,000" in text)
    check("body has a status label", "rate_limited" in text)
    check("body has top user", "user-a" in text)
    check("body has projection", "projection" in text.lower() or "projected" in text.lower())

    # --- claim_tier dedup ---
    calls = []
    def write_win(sql, params=None):
        calls.append((sql, params)); return 1   # row inserted
    def write_lose(sql, params=None):
        return 0                                  # ON CONFLICT, nothing inserted
    check("claim win", claim_tier(write_win, 80) is True)
    check("claim uses ON CONFLICT", "ON CONFLICT" in calls[0][0])
    check("claim lose", claim_tier(write_lose, 80) is False)

    # --- send_email: no key -> no send, no raise ---
    old = os.environ.pop("RESEND_API_KEY", None)
    sent = {"n": 0}
    def fake_send(payload): sent["n"] += 1; return True
    check("no key -> skip", send_email("s", "t") is False and sent["n"] == 0)
    if old is not None: os.environ["RESEND_API_KEY"] = old

    # --- maybe_alert: crosses 50+80, both claims win -> 2 sends ---
    sent_subjects = []
    def send_capture(payload): sent_subjects.append(payload["subject"]); return True
    def write_all_win(sql, params=None): return 1
    tiers = maybe_alert(q, q_one, write_all_win, num_keys=3, send_fn=send_capture)
    check("maybe_alert sends crossed tiers", tiers == [50, 80] and len(sent_subjects) == 2)

    # --- maybe_alert: tier already claimed (write returns 0) -> no send ---
    sent2 = []
    def write_none(sql, params=None): return 0
    tiers2 = maybe_alert(q, q_one, write_none, num_keys=3, send_fn=lambda p: sent2.append(1) or True)
    check("maybe_alert dedup -> no send", tiers2 == [] and sent2 == [])

    # --- maybe_alert: send_fn raises -> caught, returns cleanly ---
    def send_boom(payload): raise RuntimeError("resend down")
    try:
        maybe_alert(q, q_one, lambda s, p=None: 1, num_keys=3, send_fn=send_boom)
        check("maybe_alert swallows send error", True)
    except Exception:
        check("maybe_alert swallows send error", False)

    print("ALL PASS" if not fails else f"{len(fails)} FAIL(s): " + ", ".join(fails))
    return 1 if fails else 0


def main():
    p = argparse.ArgumentParser(description="Daily usage-alert email.")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        sys.exit(selftest())
    print("import-only module; use --selftest")


if __name__ == "__main__":
    main()
