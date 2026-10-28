"""Daily email to the team when held ratings, comments, or new professors and courses wait for review.

    python review_digest.py            # send, if anything is waiting
    python review_digest.py --dry-run  # print the email, send nothing

Runs from .github/workflows/review-digest.yml. One email a day at most and none
when the queue is empty, so it fits Resend's free 100/day next to the feedback
caps and usage alerts (see FEEDBACK_DAILY_LIMIT in server.py). Counts only: no
comments, hashes or network data. Reads ORACLE_DATABASE_URL and RESEND_API_KEY.
"""

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import notify
from pipeline.db import connect, fetch_all

TOP = 5


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _counts(counter, limit=None):
    return [f"  {k}: {v}" for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def build_digest(held, pending_professors, pending_courses, now, pending_comments=0):
    """(subject, text), or None when nothing is waiting. Pure."""
    if not held and not pending_professors and not pending_courses and not pending_comments:
        return None
    recent = [r for r in held if r["created_at"] >= now - timedelta(days=1)]
    reasons = Counter(x for r in held for x in (r["hold_reasons"] or "").split(",") if x)
    subject = (f"[RateMyHusky] To review: {_plural(len(held), 'held rating')}, "
               f"{_plural(pending_comments, 'comment')}, "
               f"{_plural(pending_professors, 'new professor')}, {_plural(pending_courses, 'new course')}")
    lines = [f"Held ratings: {len(held)} ({len(recent)} in the last 24 hours)",
             *_counts(reasons)]
    if recent:
        lines += ["", "Most held in the last 24 hours:",
                  *_counts(Counter(r["professor_slug"] for r in recent if r["professor_slug"]), TOP),
                  *_counts(Counter(r["course_code"] for r in recent if r["course_code"]), TOP)]
    lines += ["", f"Comments to review: {pending_comments}",
              f"New professors to review: {pending_professors}",
              f"New courses to review: {pending_courses}",
              "", "Review with: python review_ratings.py list"]
    return subject, "\n".join(lines)


def main(argv=None, now=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    conn = connect()
    try:
        held = fetch_all(conn, "SELECT professor_slug, course_code, hold_reasons, created_at "
                               "FROM survey_ratings WHERE status = 'held'")
        comments = fetch_all(conn, "SELECT count(*) AS n FROM survey_ratings WHERE comment_status = 'pending'")
        professors = fetch_all(conn, "SELECT count(*) AS n FROM survey_pending_professors WHERE status = 'pending'")
        courses = fetch_all(conn, "SELECT count(*) AS n FROM survey_pending_courses WHERE status = 'pending'")
    finally:
        conn.close()
    digest = build_digest(held, professors[0]["n"], courses[0]["n"], now or datetime.now(timezone.utc),
                          comments[0]["n"])
    if digest is None:
        print("nothing to review")
        return 0
    subject, text = digest
    if args.dry_run:
        print(f"{subject}\n\n{text}")
        return 0
    return 0 if notify.send_team_email(subject, text) else 1


if __name__ == "__main__":
    sys.exit(main())
