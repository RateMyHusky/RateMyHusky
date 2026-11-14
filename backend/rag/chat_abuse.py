import sys, argparse

STRIKE_STATUSES = ("injection_blocked", "off_topic", "defamation_framing")
_WARN = "I can only answer questions about Northeastern professors and courses."
_CAP_MSG = "You've hit today's question limit. Try again tomorrow, or use keyword search."
_BAN_MSG = ("Your access to the question feature has been suspended for repeated misuse. "
            "You can appeal through the feedback form.")
# strike count -> that day's question cap (strikes 1-2 = warn-only; 6+ = ban, handled separately)
_CAPS = {3: 5, 4: 3, 5: 1}
# strikes age out: only the last N days count, so a transient bad streak (or an old mistake)
# doesn't pin an account on the cap/ban ladder forever.
STRIKE_WINDOW_DAYS = 7

def strike_count(session_token, query_one_fn):
    row = query_one_fn(
        "SELECT count(*) AS c FROM ask_log "
        "WHERE session_token = %s AND result_status = ANY(%s) "
        "AND created_at > now() - %s * INTERVAL '1 day'",
        (session_token, list(STRIKE_STATUSES), STRIKE_WINDOW_DAYS))
    return (row or {}).get("c", 0) or 0

def daily_question_count(session_token, query_one_fn):
    # Issue 26: sargable predicate (created_at >= date_trunc(...)) instead of wrapping
    # the column, so this can use an index instead of scanning the whole history.
    row = query_one_fn(
        "SELECT count(*) AS c FROM ask_log "
        "WHERE session_token = %s AND mode = 'question' "
        "AND created_at >= date_trunc('day', now())",
        (session_token,))
    return (row or {}).get("c", 0) or 0

def abuse_check(session_token, query_one_fn):
    strikes = strike_count(session_token, query_one_fn)
    if strikes >= 6:
        return {"allowed": False, "banned": True, "message": _BAN_MSG}
    if strikes >= 3:
        cap = _CAPS[min(strikes, 5)]
        used = daily_question_count(session_token, query_one_fn)
        if used >= cap:
            return {"allowed": False, "banned": False, "message": _CAP_MSG}
        return {"allowed": True, "banned": False, "message": None}
    if strikes >= 1:
        return {"allowed": True, "banned": False, "message": _WARN}
    return {"allowed": True, "banned": False, "message": None}

# What a kept strike's question becomes after a data deletion.
DELETED_TEXT = "[deleted at the user's request]"
_LIVE_STRIKE = ("result_status = ANY(%s) AND created_at > now() - %s * INTERVAL '1 day'")

def account_data_counts(cur, account):
    """What delete_account_data would touch: all Ask rows, the strikes that still count,
    and bookmarks."""
    cur.execute(
        "SELECT count(*), count(*) FILTER (WHERE " + _LIVE_STRIKE + ") "
        "FROM ask_log WHERE session_token = %s",
        (list(STRIKE_STATUSES), STRIKE_WINDOW_DAYS, account))
    rows, strikes = cur.fetchone()
    cur.execute("SELECT count(*) FROM bookmarks WHERE user_sub = %s", (account,))
    return {"ask_rows": rows, "live_strikes": strikes, "bookmarks": cur.fetchone()[0]}

def delete_account_data(cur, account, keep_standing):
    """Erase one account's Ask questions and bookmarks; the caller commits.

    keep_standing=True is a data deletion: the account stays, and so does its Ask standing.
    The strikes that still count are kept with their text removed, so a warning, cap or
    ban carries on and lapses on its usual STRIKE_WINDOW_DAYS schedule. keep_standing=False
    is an account deletion: every row goes, strikes and any ban included."""
    kept = 0
    if keep_standing:
        cur.execute(
            "UPDATE ask_log SET query = %s, answer_text = NULL, professor_slug = NULL, ip_hash = NULL "
            "WHERE session_token = %s AND " + _LIVE_STRIKE,
            (DELETED_TEXT, account, list(STRIKE_STATUSES), STRIKE_WINDOW_DAYS))
        kept = cur.rowcount
        # now() is fixed for the transaction, so this spares exactly the rows kept above.
        # IS NOT TRUE, not NOT: a row with a NULL created_at must be deleted too.
        cur.execute(
            "DELETE FROM ask_log WHERE session_token = %s AND (" + _LIVE_STRIKE + ") IS NOT TRUE",
            (account, list(STRIKE_STATUSES), STRIKE_WINDOW_DAYS))
    else:
        cur.execute("DELETE FROM ask_log WHERE session_token = %s", (account,))
    deleted = cur.rowcount
    cur.execute("DELETE FROM bookmarks WHERE user_sub = %s", (account,))
    return {"deleted": deleted, "kept_strikes": kept, "bookmarks_deleted": cur.rowcount}

def selftest():
    fails = []
    def check(label, cond):
        if not cond: fails.append(label)
        print(("PASS" if cond else "FAIL") + ": " + label)

    seen = {}
    def make_q(strikes, today):
        def q(sql, params=None):
            if "result_status = ANY" in sql:
                seen["strike_sql"] = sql
                seen["strike_params"] = params
                return {"c": strikes}
            return {"c": today}
        return q

    r0 = abuse_check("s", make_q(0, 0))
    check("no strikes allowed", r0["allowed"] is True and r0["banned"] is False)
    # strikes must age out: the count query is windowed (rolling STRIKE_WINDOW_DAYS), not all-time.
    check("strike query is time-windowed", "INTERVAL '1 day'" in seen["strike_sql"])
    check("strike query passes the window size", STRIKE_WINDOW_DAYS in seen["strike_params"])

    r1 = abuse_check("s", make_q(1, 0))
    check("first strike warns but allows", r1["allowed"] is True and r1["message"])

    r2 = abuse_check("s", make_q(2, 0))   # still in the 1-2 warn tier
    check("second strike warns but allows", r2["allowed"] is True and r2["banned"] is False and r2["message"])

    r3_under = abuse_check("s", make_q(3, 4))   # cap 5/day, used 4 → allowed
    check("3rd strike under 5/day allowed", r3_under["allowed"] is True)
    r3_over = abuse_check("s", make_q(3, 5))    # cap 5/day, used 5 → denied
    check("3rd strike at 5/day denied", r3_over["allowed"] is False and r3_over["banned"] is False)

    r4_under = abuse_check("s", make_q(4, 2))   # cap 3/day, used 2 → allowed
    check("4th strike under 3/day allowed", r4_under["allowed"] is True)

    r5_over = abuse_check("s", make_q(5, 1))    # cap 1/day, used 1 → denied
    check("5th strike at 1/day denied", r5_over["allowed"] is False)

    r6 = abuse_check("s", make_q(6, 0))
    check("6th strike banned with appeal", r6["banned"] is True and "feedback" in r6["message"].lower())

    # Issue 26: daily_question_count predicate must be sargable (no date_trunc(created_at))
    seen_daily = {}
    def q_daily(sql, params=None):
        seen_daily["sql"] = sql
        return {"c": 1}
    daily_question_count("s", q_daily)
    check("daily_question_count has no date_trunc(created_at)",
          "date_trunc('day', created_at)" not in seen_daily["sql"])
    check("daily_question_count uses sargable created_at >= date_trunc",
          "created_at >= date_trunc('day', now())" in seen_daily["sql"])

    print("ALL PASS" if not fails else f"{len(fails)} FAIL(s): " + ", ".join(fails))
    return 1 if fails else 0

def main():
    p = argparse.ArgumentParser(description="Graduated abuse ladder (session-keyed).")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        sys.exit(selftest())
    print("import-only module; use --selftest")

if __name__ == "__main__":
    main()
