import sys, argparse, threading, time
from datetime import datetime, timezone, timedelta

# ~80 = measured ceiling: gpt-oss-120b 200K TPD / ~2500 tokens per answered question.
# (Was 100, based on a 1800-tok estimate; live testing showed ~2500/Q, so 80 is the honest cap.)
PER_KEY_DAILY = 80
SAFE_THRESHOLD = 0.85
CONSTRAINED_SESSION_CAP = 3
# Applies at all times, so a handful of accounts can't spend the shared daily
# budget before the 85% threshold switches the tighter cap on.
SESSION_DAILY_CAP = 20

# Per-minute (TPM) limits — the real concurrency bottleneck. gpt-oss-120b free tier = 8K tokens/min
# per key (confirmed from the Groq dashboard). Each answered question costs ~2500 tokens end-to-end
# (gate + synth, incl. reasoning), so one key sustains only ~3 questions/min.
TPM_PER_KEY = 8000
EST_TOKENS_PER_Q = 2500

def daily_budget(num_keys):
    return PER_KEY_DAILY * max(num_keys, 1)

def minute_token_budget(num_keys):
    return TPM_PER_KEY * max(num_keys, 1)

# --- Issue 18: check-then-act race guard -----------------------------------
# Railway runs a single process; gunicorn threads share this memory, so a
# module-level lock + in-flight reservation counters close the race between
# reading today's DB count and the ask_log INSERT that will record it.
# In-flight reservations expire on their own (RESERVATION_TTL) so a request
# that never calls release_reservation() (e.g. it crashes) can't wedge the
# counters open forever. Multi-worker/multi-process deployments would need a
# DB-side reservation instead — not implemented here.
RESERVATION_TTL = 30  # seconds; well over the slowest expected generate() call
_reservation_lock = threading.Lock()
_reservations = {"daily": [], "minute_tokens": []}  # list of (expires_at, amount)

def _sweep_reservations(now_ts, kind):
    _reservations[kind] = [(exp, amt) for exp, amt in _reservations[kind] if exp > now_ts]

def release_reservation(kind, amount=1):
    """Call in a `finally` around generate() once the ask_log row has been written,
    so the in-flight reservation doesn't double-count once the DB reflects it."""
    now_ts = time.time()
    with _reservation_lock:
        for i, (exp, amt) in enumerate(_reservations[kind]):
            if amt == amount:
                del _reservations[kind][i]
                return
        # nothing to release (already expired/swept) — no-op

def tokens_used_last_minute(query_one_fn, now=None):
    """Sum tokens_used across the pool over the last 60s (from ask_log). Proactive TPM guard:
    lets the throttle degrade gracefully BEFORE Groq returns a 429."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=60)
    row = query_one_fn(
        "SELECT coalesce(sum(tokens_used), 0) AS t FROM ask_log WHERE created_at > %s",
        (cutoff,))
    return (row or {}).get("t", 0) or 0

def minute_capacity_ok(query_one_fn, num_keys, est_tokens=EST_TOKENS_PER_Q, now=None):
    """True if this question fits under the pool's per-minute token ceiling (with safety margin).
    False => the minute is saturated; the orchestrator must degrade to keyword fallback (no LLM call).
    Issue 18: reserves est_tokens under the lock on a True verdict, so concurrent in-flight
    requests are visible to each other before any of their ask_log rows exist. Callers should
    release_reservation("minute_tokens", est_tokens) once tokens_used is actually logged."""
    with _reservation_lock:
        now_ts = time.time()
        _sweep_reservations(now_ts, "minute_tokens")
        used = tokens_used_last_minute(query_one_fn, now)
        in_flight = sum(amt for _, amt in _reservations["minute_tokens"])
        if used + in_flight + est_tokens > minute_token_budget(num_keys) * SAFE_THRESHOLD:
            return False
        _reservations["minute_tokens"].append((now_ts + RESERVATION_TTL, est_tokens))
        return True

def _today_ok_count(query_one_fn, today_count_memo=None):
    # Issue 26: sargable predicate (`created_at >= date_trunc(...)` instead of
    # wrapping the column) so the al_status/created_at index can drive this,
    # instead of a full scan of every historical 'ok' row.
    # today_count_memo lets a caller that already fetched this once this request
    # (global_budget_hit + session_allowed->projected_daily_usage both need it)
    # pass it straight through instead of querying twice. Default (None) preserves
    # the original always-query behavior for any caller that doesn't thread it.
    # Issue 7: this feeds global_budget_hit/projected_daily_usage, which meter LLM
    # spend — cache hits ('ok_cached') cost zero tokens and must NOT count here.
    if today_count_memo is not None:
        return today_count_memo
    row = query_one_fn(
        "SELECT count(*) AS c FROM ask_log "
        "WHERE created_at >= date_trunc('day', now()) AND result_status = 'ok'")
    return (row or {}).get("c", 0) or 0

def today_ok_count(query_one_fn, today_count_memo=None):
    """Public wrapper (Issue 26): lets callers outside this module fetch today's
    'ok' count once and thread it into both global_budget_hit and session_allowed
    via today_count_memo, instead of each calling the private helper separately."""
    return _today_ok_count(query_one_fn, today_count_memo)

def projected_daily_usage(query_one_fn, now=None, today_count_memo=None):
    now = now or datetime.now(timezone.utc)
    minute_of_day = now.hour * 60 + now.minute
    if minute_of_day < 30:
        return 0
    calls = _today_ok_count(query_one_fn, today_count_memo)
    return int((calls / minute_of_day) * 1440)

def is_constrained(query_one_fn, num_keys, now=None, today_count_memo=None):
    return projected_daily_usage(query_one_fn, now, today_count_memo) > daily_budget(num_keys) * SAFE_THRESHOLD

def global_budget_hit(query_one_fn, num_keys, today_count_memo=None):
    """Issue 18: reserve-then-check under a lock so concurrent requests can't all
    read the same DB count and all pass. Returns True (budget hit, caller must
    fall back) or False (allowed — and reserves a slot so the next concurrent
    caller sees it). Callers that get `False` (allowed) should release the
    reservation via release_reservation("daily") once the ask_log row for this
    question has actually been written (in a `finally` around generate())."""
    with _reservation_lock:
        now_ts = time.time()
        _sweep_reservations(now_ts, "daily")
        db_count = _today_ok_count(query_one_fn, today_count_memo)
        in_flight = sum(amt for _, amt in _reservations["daily"])
        if db_count + in_flight >= daily_budget(num_keys):
            return True
        _reservations["daily"].append((now_ts + RESERVATION_TTL, 1))
        return False

def session_allowed(session_token, query_one_fn, num_keys, now=None, today_count_memo=None):
    cap = (CONSTRAINED_SESSION_CAP if is_constrained(query_one_fn, num_keys, now, today_count_memo)
           else SESSION_DAILY_CAP)
    # Issue 19: this is a per-DAY cap (matches the "today's question limit" banner),
    # not the 60s window it used to check — and it must count cache hits too (Issue 7's
    # 'ok_cached' status), since those are still successful answers from the user's POV.
    row = query_one_fn(
        "SELECT count(*) AS c FROM ask_log "
        "WHERE session_token = %s AND created_at >= date_trunc('day', now()) "
        "AND result_status = ANY(%s)",
        (session_token, ["ok", "ok_cached"]))
    if ((row or {}).get("c", 0) or 0) >= cap:
        return False, "rate_limited"
    return True, None

def _count_adapter(fn):
    # adapt the test's dict-returning fn to query_one_fn shape
    return fn

def selftest():
    fails = []
    def check(label, cond):
        if not cond: fails.append(label)
        print(("PASS" if cond else "FAIL") + ": " + label)

    noon = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)  # minute_of_day = 720

    # budget scales with key count: 1 key -> 80/day, 3 keys -> 240/day
    check("budget scales per key", daily_budget(1) == 80 and daily_budget(3) == 240)
    check("budget floors at 1 key", daily_budget(0) == 80)

    # 3 keys -> budget 240, threshold 0.85*240 = 204.
    # 120 ok-calls by noon -> rate 120/720/min -> *1440 = 240 projected > 204 -> constrained
    def q1(sql, params=None): return {"c": 120}
    check("busy day projects over threshold", is_constrained(_count_adapter(q1), num_keys=3, now=noon) is True)

    def q0(sql, params=None): return {"c": 5}
    check("quiet day not constrained", is_constrained(_count_adapter(q0), num_keys=3, now=noon) is False)

    # global backstop at the pool budget (3 keys -> 240)
    def qfull(sql, params=None): return {"c": 240}
    check("global budget hit at pool ceiling", global_budget_hit(_count_adapter(qfull), num_keys=3) is True)

    # per-session cap only bites in constrained mode
    def q_session(sql, params=None):
        # return projection-high for the day count, and 3 recent for the session count
        return {"c": 3} if "session_token" in sql else {"c": 120}
    ok, status = session_allowed("sess1", _count_adapter(q_session), num_keys=3, now=noon)
    check("constrained session over cap denied", ok is False and status == "rate_limited")

    # normal (quiet) mode: session is always allowed
    ok2, status2 = session_allowed("sess1", _count_adapter(q0), num_keys=3, now=noon)
    check("normal-mode session allowed", ok2 is True and status2 is None)

    # --- per-minute TPM throttle ---
    check("minute budget scales per key", minute_token_budget(1) == 8000 and minute_token_budget(3) == 24000)
    check("minute budget floors at 1 key", minute_token_budget(0) == 8000)

    # 3 keys -> 24000/min budget, 0.85*24000 = 20400 usable.
    # quiet minute (2000 tok used) + one ~2500-tok question = 4500 <= 20400 -> OK
    # (Issue 18: an allowed call reserves est_tokens, so release it immediately to keep
    # each check below isolated from the others' in-flight reservations.)
    def q_quiet_min(sql, params=None): return {"t": 2000}
    check("quiet minute admits a question",
          minute_capacity_ok(_count_adapter(q_quiet_min), num_keys=3, now=noon) is True)
    release_reservation("minute_tokens", EST_TOKENS_PER_Q)

    # saturated minute (20000 tok used) + 2500 = 22500 > 20400 -> NOT ok (degrade to keyword)
    def q_busy_min(sql, params=None): return {"t": 20000}
    check("saturated minute rejects a question",
          minute_capacity_ok(_count_adapter(q_busy_min), num_keys=3, now=noon) is False)

    # single key, 1 in-flight question's worth already used (2500) + 2500 = 5000 vs 0.85*8000=6800 -> OK
    def q_onekey(sql, params=None): return {"t": 2500}
    check("1 key admits a 2nd question in the minute",
          minute_capacity_ok(_count_adapter(q_onekey), num_keys=1, now=noon) is True)
    release_reservation("minute_tokens", EST_TOKENS_PER_Q)
    # 1 key, 3 questions already (7500) + 2500 = 10000 > 6800 -> NOT ok
    def q_onekey_full(sql, params=None): return {"t": 7500}
    check("1 key rejects the 4th question in the minute",
          minute_capacity_ok(_count_adapter(q_onekey_full), num_keys=1, now=noon) is False)

    # --- Issue 19: session cap counts the whole day (and 'ok_cached'), not a 60s window ---
    seen_session_sql = {}
    def q_day_status(sql, params=None):
        seen_session_sql["sql"] = sql
        seen_session_sql["params"] = params
        return {"c": 3} if "session_token" in sql else {"c": 120}
    ok3, status3 = session_allowed("sess1", _count_adapter(q_day_status), num_keys=3, now=noon)
    check("session cap counts across the whole day", "date_trunc('day', now())" in seen_session_sql["sql"])
    check("session cap query has no 60s cutoff param", len(seen_session_sql["params"]) == 2)
    check("session cap counts ok + ok_cached", seen_session_sql["params"][1] == ["ok", "ok_cached"])
    check("day cap of 3 denies the session", ok3 is False and status3 == "rate_limited")

    def q_two_today(sql, params=None):
        return {"c": 2} if "session_token" in sql else {"c": 120}
    ok4, status4 = session_allowed("sess1", _count_adapter(q_two_today), num_keys=3, now=noon)
    check("2 today (under cap of 3) allowed", ok4 is True and status4 is None)

    # --- Issue 26: sargable predicate, no date_trunc(column), and a memo avoids the 2nd query ---
    check("_today_ok_count predicate is sargable (no date_trunc on created_at)",
          "date_trunc('day', created_at)" not in seen_session_sql["sql"])
    seen_daily_sql = {}
    def q_track(sql, params=None):
        seen_daily_sql["sql"] = sql
        return {"c": 7}
    check("_today_ok_count sargable + counts ok only (Issue 7: not ok_cached)",
          _today_ok_count(_count_adapter(q_track)) == 7)
    check("no date_trunc(created_at) in _today_ok_count SQL",
          "date_trunc('day', created_at)" not in seen_daily_sql["sql"])
    check("_today_ok_count filters result_status = 'ok', not ok_cached",
          "result_status = 'ok'" in seen_daily_sql["sql"] and "ok_cached" not in seen_daily_sql["sql"])
    check("_today_ok_count memo skips the query entirely",
          _today_ok_count(lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not query")), today_count_memo=42) == 42)

    # --- Issue 18: concurrent global_budget_hit reservations are visible to each other ---
    def q_near_limit(sql, params=None): return {"c": 79}  # 1 key -> budget 80
    hit1 = global_budget_hit(_count_adapter(q_near_limit), num_keys=1)
    check("first caller at 79/80 is allowed (reserves a slot)", hit1 is False)
    hit2 = global_budget_hit(_count_adapter(q_near_limit), num_keys=1)
    check("second concurrent caller sees the in-flight reservation and is blocked", hit2 is True)
    release_reservation("daily", 1)
    hit3 = global_budget_hit(_count_adapter(q_near_limit), num_keys=1)
    check("after release, a caller is allowed again", hit3 is False)
    release_reservation("daily", 1)  # clean up so later runs of selftest() start fresh

    # real thread race: both threads read the same DB count (budget-1); with the lock+
    # reservation, exactly one must be allowed, not both (the original check-then-act bug).
    results = []
    barrier = threading.Barrier(2)
    def race_worker():
        barrier.wait()
        results.append(global_budget_hit(_count_adapter(q_near_limit), num_keys=1))
    t1 = threading.Thread(target=race_worker)
    t2 = threading.Thread(target=race_worker)
    t1.start(); t2.start()
    t1.join(); t2.join()
    check("exactly one of two racing threads is allowed", sorted(results) == [False, True])
    release_reservation("daily", 1)  # whichever thread's reservation is still outstanding

    def q_near_minute_limit(sql, params=None): return {"t": 4300}  # 1 key -> 8000*0.85=6800 usable
    ok_m1 = minute_capacity_ok(_count_adapter(q_near_minute_limit), num_keys=1, now=noon)
    check("first minute caller near cap (4300+2500=6800) allowed", ok_m1 is True)
    ok_m2 = minute_capacity_ok(_count_adapter(q_near_minute_limit), num_keys=1, now=noon)
    check("second concurrent minute caller sees the reservation and is blocked",
          ok_m2 is False)
    release_reservation("minute_tokens", EST_TOKENS_PER_Q)

    print("ALL PASS" if not fails else f"{len(fails)} FAIL(s): " + ", ".join(fails))
    return 1 if fails else 0

def main():
    p = argparse.ArgumentParser(description="Adaptive question-path throttle.")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        sys.exit(selftest())
    print("import-only module; use --selftest")

if __name__ == "__main__":
    main()
