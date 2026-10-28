"""Check the rating comments the submit couldn't: Groq was busy or down, or the sender was over budget.

    python moderate_queue.py   # check up to BATCH comments that are due

Runs every 10 minutes from .github/workflows/moderate-queue.yml. Without
GROQ_MODERATION_KEY it does nothing and exits 0; it never calls OpenAI, whose
free allowance production shares (see moderation.py). Reads ORACLE_DATABASE_URL.
Prints counts only: no comment text, hashes or network data.

Only comments still waiting for review are checked, returning devices first and
over-budget ones last, oldest first within each. A verdict only sorts
`review_ratings.py list`, except a block: that holds the rating as
moderation_block, so its numbers stop counting until a reviewer looks. It stops
at the first 429, and once the day's model calls (submit and queue) reach
DAILY_CAP, which leaves room for submits under Groq's 1,000 a day. A failed check
backs off and is tried again later, without end; the reviewer can approve or
reject it at any time.
"""

import sys
import time
from datetime import datetime, timedelta, timezone

from psycopg2.extras import RealDictCursor

import moderation_groq
import ratings
from pipeline.db import connect
from pipeline.read_models import DATA_VERSION_SQL

BATCH = 15
SPACING_SECONDS = 21  # under Groq's 3 requests a minute
DAILY_CAP = 800
NEXT_RUN = timedelta(minutes=10)
BASE_BACKOFF = timedelta(minutes=10)
MAX_BACKOFF = timedelta(hours=6)

_DUE_SQL = (
    "SELECT id::text AS id, comment, comment_check_attempts FROM survey_ratings "
    "WHERE comment_check = 'unchecked' AND comment_next_check_at <= %s "
    "AND comment_status = 'pending' AND comment IS NOT NULL "
    "ORDER BY COALESCE(comment_check_reason = 'over_budget', false), new_device, updated_at LIMIT %s")
# The text checked must still be the row's, waiting and unchecked: an edit, an
# approval or a rejection since the row was read leaves it alone.
_STILL_DUE = ("WHERE id::text = %s AND comment = %s AND comment_check = 'unchecked' "
              "AND comment_status = 'pending'")


def backoff(attempts):
    """The wait after a failed check, from the checks tried before it."""
    return min(BASE_BACKOFF * 2 ** attempts, MAX_BACKOFF)


def calls_today(cur, now):
    cur.execute("SELECT count(*) AS n FROM moderation_calls WHERE called_at >= %s", (now - timedelta(days=1),))
    return cur.fetchone()["n"]


def record(cur, row, action, reason, now):
    """Store one check result; True when it held the rating."""
    attempts = (row["comment_check_attempts"] or 0) + 1
    if action in ("allow", "review"):
        cur.execute(f"UPDATE survey_ratings SET comment_check = %s, comment_check_reason = %s, "
                    f"comment_check_attempts = %s, comment_next_check_at = NULL, comment_checked_at = %s "
                    f"{_STILL_DUE}", (action, reason, attempts, now, row["id"], row["comment"]))
        return False
    if action == "block":
        # Flagged rather than dropped, so the reviewer reads it and can reject-comment.
        cur.execute("UPDATE survey_ratings SET comment_check = 'review', comment_check_reason = 'blocked', "
                    "comment_check_attempts = %s, comment_next_check_at = NULL, comment_checked_at = %s, "
                    "status = 'held', hold_reasons = CASE "
                    "WHEN hold_reasons IS NULL THEN 'moderation_block' "
                    "WHEN ',' || hold_reasons || ',' LIKE '%%,moderation_block,%%' THEN hold_reasons "
                    f"ELSE hold_reasons || ',moderation_block' END {_STILL_DUE}",
                    (attempts, now, row["id"], row["comment"]))
        return cur.rowcount == 1
    wait = NEXT_RUN if reason == "groq_rate_limited" else backoff(row["comment_check_attempts"] or 0)
    cur.execute(f"UPDATE survey_ratings SET comment_check_reason = %s, comment_check_attempts = %s, "
                f"comment_next_check_at = %s {_STILL_DUE}", (reason, attempts, now + wait, row["id"], row["comment"]))
    return False


def run(conn, groq, now=None, sleep=time.sleep):
    """Check what's due; return a one-line summary. Commits after each comment, so
    a run cut short keeps what it did."""
    now_fn = (lambda: now) if now else (lambda: datetime.now(timezone.utc))
    counts = {"allow": 0, "review": 0, "block": 0, "unavailable": 0}
    stopped = ""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(_DUE_SQL, (now_fn(), BATCH))
        due = cur.fetchall()
        conn.commit()
        for i, row in enumerate(due):
            if calls_today(cur, now_fn()) >= DAILY_CAP:
                stopped = f", stopped at the daily cap of {DAILY_CAP}"
                break
            if i:
                sleep(SPACING_SECONDS)
            action, reason = moderation_groq.check(row["comment"], groq)
            at = now_fn()
            ratings.record_moderation_call("queue", action, None, None, False,
                                           lambda sql, params: cur.execute(sql, params), at)
            if record(cur, row, action, reason, at):
                cur.execute(DATA_VERSION_SQL)  # the professor page drops the held rating's numbers
            conn.commit()
            counts[action] += 1
            if reason == "groq_rate_limited":
                rest = [r["id"] for r in due[i + 1:]]
                if rest:
                    cur.execute("UPDATE survey_ratings SET comment_next_check_at = %s "
                                "WHERE id::text = ANY(%s) AND comment_check = 'unchecked'", (at + NEXT_RUN, rest))
                    conn.commit()
                stopped = ", stopped at a 429"
                break
    return (f"{len(due)} due: {counts['allow']} clean, {counts['review']} flagged, {counts['block']} blocked, "
            f"{counts['unavailable']} failed{stopped}")


def main():
    if not moderation_groq.enabled():
        print("GROQ_MODERATION_KEY is not set; nothing to do")
        return 0
    conn = connect()
    try:
        print(run(conn, moderation_groq.client()))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
