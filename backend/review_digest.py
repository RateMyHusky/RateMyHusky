"""Daily email to the team when held ratings or new professors and courses wait for review.

    python review_digest.py            # send, if anything is waiting
    python review_digest.py --dry-run  # print the email, send nothing

Runs from .github/workflows/review-digest.yml. One email a day at most and none
when the queue is empty, so it fits Resend's free 100/day next to the feedback
caps and usage alerts (see FEEDBACK_DAILY_LIMIT in server.py). Counts, slugs,
course codes, hold reasons and rating ids only: no comments, agent reasons,
hashes or network data. Reads ORACLE_DATABASE_URL and RESEND_API_KEY.
"""

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import notify
from review_agent import decision_of, group_held, reasons_of
from pipeline.db import connect, fetch_all

TOP = 5


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _counts(counter, limit=None):
    return [f"  {k}: {v}" for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def _short(row):
    return str(row["id"])[:8]


def _attack_lines(group):
    group = sorted(group, key=lambda r: r["created_at"])
    first, last = (group[i]["created_at"].astimezone(timezone.utc) for i in (0, -1))
    reasons = sorted(reasons_of(group))
    slug = group[0]["professor_slug"] or "pending-professor"
    end = f"{last:%H:%M}" if last.date() == first.date() else f"{last:%Y-%m-%d %H:%M}"
    return [f"  {slug}: {_plural(len(group), 'rating')}, "
            f"{first:%Y-%m-%d %H:%M}-{end} UTC [{', '.join(reasons)}]",
            f"    python review_ratings.py reject-rating --abuse {' '.join(_short(r) for r in group)}"]


def build_digest(held, approved, pending_professors, pending_courses, now, course_merges=(), professor_merges=(), aliases=()):
    """(subject, text), or None when nothing is waiting. Pure."""
    if not held and not approved and not pending_professors and not pending_courses and not course_merges \
            and not professor_merges and not aliases:
        return None
    recent = [r for r in held if r["created_at"] >= now - timedelta(days=1)]
    reasons = Counter(x for r in held for x in (r["hold_reasons"] or "").split(",") if x)
    subject = (f"[RateMyHusky] To review: {_plural(len(held), 'held rating')}, "
               f"{_plural(pending_professors, 'new professor')}, {_plural(pending_courses, 'new course')}")
    if aliases:
        subject += f", {_plural(len(aliases), 'nickname suggestion')}"
    if course_merges or professor_merges:
        subject += f", {_plural(len(course_merges) + len(professor_merges), 'agent merge')}"
    lines = [f"Held ratings: {len(held)} ({len(recent)} in the last 24 hours)",
             *_counts(reasons)]
    if recent:
        lines += ["", "Most held in the last 24 hours:",
                  *_counts(Counter(r["professor_slug"] for r in recent if r["professor_slug"]), TOP),
                  *_counts(Counter(r["course_code"] for r in recent if r["course_code"]), TOP)]
    attacks = group_held([r for r in held if decision_of(r) == "reject"])
    if attacks:
        lines += ["", f"Recommended rejections: {_plural(len(attacks), 'attack')}",
                  *(line for g in attacks for line in _attack_lines(g))]
    escalated = sum(decision_of(r) == "escalate" for r in held)
    unreviewed = sum(decision_of(r) is None for r in held)
    if escalated or unreviewed:
        lines += ["", f"Escalated without a recommendation: {escalated}",
                  f"Not yet reviewed by the agent: {unreviewed}"]
    if approved:
        lines += ["", f"Agent approved in the last 24 hours: {len(approved)}",
                  *(f"  {_short(r)} {r['professor_slug'] or 'pending-professor'} {r['course_code'] or '-'} "
                    f"[{', '.join(x for x in (r['hold_reasons'] or '').split(',') if x)}]" for r in approved)]
    if course_merges:
        lines += ["", f"Agent course merges in the last 24 hours: {len(course_merges)}",
                  *(f"  {m['code']} -> {m['resolved_code']} ({_plural(m['n'], 'rating')})" for m in course_merges)]
    if professor_merges:
        lines += ["", f"Agent professor merges in the last 24 hours: {len(professor_merges)}",
                  *(f"  {m['id'][:8]} -> {m['resolved_slug']} ({_plural(m['n'], 'rating')})" for m in professor_merges)]
    if aliases:
        lines += ["", f"Nickname suggestions: {len(aliases)}",
                  *(f"  #{a['id']} {a['alias_key']} -> {a['slug']} ({a['source']})" for a in aliases),
                  "Approve with: python review_ratings.py approve-alias ID"]
    lines += ["", f"New professors to review: {pending_professors}",
              f"New courses to review: {pending_courses}",
              "", "Review with: python review_ratings.py list"]
    return subject, "\n".join(lines)


def main(argv=None, now=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    conn = connect()
    try:
        cols = ("id::text AS id, professor_slug, pending_professor_id::text AS pending_professor_id, "
                "course_code, hold_reasons, agent_decision, agent_reviewed_at, updated_at, created_at")
        held = fetch_all(conn, f"SELECT {cols} FROM survey_ratings WHERE status = 'held'")
        approved = fetch_all(conn, f"SELECT {cols} FROM survey_ratings WHERE status = 'accepted' "
                                   "AND agent_decision = 'approve' AND agent_reviewed_at >= now() - interval '1 day' "
                                   "ORDER BY agent_reviewed_at")
        professors = fetch_all(conn, "SELECT count(*) AS n FROM survey_pending_professors WHERE status = 'pending'")
        courses = fetch_all(conn, "SELECT count(*) AS n FROM survey_pending_courses WHERE status = 'pending'")
        # The merge's reason ends "; N rating(s)": moving the ratings cleared their link to the course.
        merges = fetch_all(conn, "SELECT code, resolved_code, COALESCE(substring(agent_reason from '([0-9]+) rating')::int, 0) "
                                 "AS n FROM survey_pending_courses WHERE status = 'merged' AND agent_decision = 'merge' "
                                 "AND agent_reviewed_at >= now() - interval '1 day' ORDER BY agent_reviewed_at")
        prof_merges = fetch_all(conn, "SELECT id::text AS id, resolved_slug, COALESCE(substring(agent_reason from '([0-9]+) rating')::int, 0) "
                                      "AS n FROM survey_pending_professors WHERE status = 'merged' AND agent_decision = 'merge' "
                                      "AND agent_reviewed_at >= now() - interval '1 day' ORDER BY agent_reviewed_at")
        aliases = fetch_all(conn, "SELECT id, alias_key, slug, source FROM professor_aliases "
                                  "WHERE status = 'pending' ORDER BY id")
    finally:
        conn.close()
    digest = build_digest(held, approved, professors[0]["n"], courses[0]["n"], now or datetime.now(timezone.utc),
                          merges, prof_merges, aliases)
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
