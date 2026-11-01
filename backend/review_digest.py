"""Daily email to the team when held ratings, comments, or new professors and courses wait for review.

    python review_digest.py            # send, if anything is waiting
    python review_digest.py --dry-run  # print the email, send nothing

Runs from .github/workflows/review-digest.yml. One email a day at most and none
when the queue is empty, so it fits Resend's free 100/day next to the feedback
caps and usage alerts (see FEEDBACK_DAILY_LIMIT in server.py). Counts, names,
course codes, hold reasons and rating ids only: no comments, agent reasons,
hashes or network data. Reads ORACLE_DATABASE_URL and RESEND_API_KEY.
"""

import argparse
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from html import escape

import digest_html as dh
import notify
from review_agent import decision_of, group_held
from pipeline.db import connect, fetch_all

_REASONS = {
    "unverified_pair": "course not taught per Banner", "unverified_term": "wrong term per Banner",
    "too_fast": "filled in too fast", "no_timer": "no form timer", "stale": "form left open too long",
    "datacenter": "sent from a data center", "skew_week": "unusual week for this professor",
    "duplicate_comment": "copied comment", "near_duplicate": "copied comment",
    "moderation_block": "comment blocked by the checker", "silent_hold": "device held after an abuse reject",
}
_RATE_NOTE = ("Each Groq bar shows whichever of requests or tokens is closer to its limit. "
              "Bars turn amber at 50% and red at 80%.")
_TABLE = 'role="presentation" width="100%" cellpadding="0" cellspacing="0"'
_MONO = "Consolas,Menlo,monospace"


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _short(row):
    return str(row["id"])[:8]


def course_label(code):
    if not code:
        return "-"
    m = re.fullmatch(r"([A-Za-z]+)(\d.*)", code)
    return f"{m[1]} {m[2]}" if m else code


def reason_label(code):
    return "rating burst" if code.startswith("burst_") else _REASONS.get(code, code)


def fmt(n):
    if n < 10_000:
        return f"{n:,}"
    if round(n / 1000) < 1000:
        return f"{round(n / 1000)}K"
    return f"{n / 1_000_000:.1f}".removesuffix(".0") + "M"


def groq_meter(label, requests, tokens, request_limit, token_limit):
    if tokens * request_limit > requests * token_limit:
        return {"label": label, "used": tokens, "limit": token_limit, "unit": "tokens"}
    return {"label": label, "used": requests, "limit": request_limit, "unit": "requests"}


def _name(slug, names):
    return "a new professor" if slug is None else (names or {}).get(slug, slug)


def _span(group):
    seconds = (group[-1]["created_at"] - group[0]["created_at"]).total_seconds()
    minutes = max(1, math.ceil(seconds / 60))
    if minutes < 120:
        return _plural(minutes, "minute")
    hours = math.ceil(seconds / 3600)
    return _plural(hours, "hour") if hours < 48 else _plural(math.ceil(seconds / 86400), "day")


def _attacks(held, names):
    out = []
    for g in group_held([r for r in held if decision_of(r) == "reject"]):
        g = sorted(g, key=lambda r: r["created_at"])
        courses = ", ".join(sorted({course_label(r["course_code"]) for r in g}))
        sentence = (f"{_plural(len(g), 'rating')} for {_name(g[0]['professor_slug'], names)} in {courses}, "
                    f"all within {_span(g)}.")
        out.append((sentence, "python review_ratings.py reject-rating --abuse " + " ".join(_short(r) for r in g)))
    return out


def _short_rows(approved, course_merges, professor_merges, aliases, names):
    items = [(f"Agent approved: {_name(r['professor_slug'], names)}, {course_label(r['course_code'])}", _short(r))
             for r in approved]
    items += [(f"Merged {course_label(m['code'])} into {course_label(m['resolved_code'])}",
               _plural(m["n"], "rating")) for m in course_merges]
    items += [(f"Merged a new professor into {_name(m['resolved_slug'], names)}",
               _plural(m["n"], "rating") + (f", {m['held']} held" if m.get("held") else ""))
              for m in professor_merges]
    items += [(f'Nickname "{a["alias_key"]}" for {_name(a["slug"], names)}', f"#{a['id']}") for a in aliases]
    return items


def _meter_shown(m):
    return f"{fmt(m['used'])} / {fmt(m['limit'])}" + (f" {m['unit']}" if m["unit"] else "")


def _limits_in_subject(meters):
    hot = sorted(((dh.pct(m["used"], m["limit"]), m["label"]) for m in meters if m.get("limit")),
                 key=lambda p: -p[0])
    return ", ".join(f"{label} at {p}%" for p, label in hot if p >= 50) or "limits OK"


def _count_label(n, word):
    return word if n == 1 else word + "s"


def build_digest(held, approved, pending_professors, pending_courses, now, course_merges=(), professor_merges=(),
                 aliases=(), pending_comments=0, flagged_comments=0, unchecked_comments=0,
                 names=None, ratings=None, meters=None):
    """(subject, text, html). Pure."""
    ratings = ratings or {"new": 0, "live": 0, "held": 0, "rejected": 0, "live_all": 0, "comments_all": 0,
                          "days": [(0, 0)] * 14}
    meters = [m for m in (meters or []) if m.get("limit") or m.get("note")]
    waiting = len(held) + pending_comments + pending_professors + pending_courses + len(aliases)
    subject = (f"[RateMyHusky] {f'{waiting} to review' if waiting else 'Nothing to review'}, "
               f"{_plural(ratings['new'], 'new rating')}, {_limits_in_subject(meters)}")
    now = now.astimezone(timezone.utc)
    dateline = f"{now:%A}, {now:%b} {now.day}. Covers the last 24 hours."

    reasons = Counter(label for r in held
                      for label in {reason_label(x) for x in (r["hold_reasons"] or "").split(",") if x})
    reason_items = [(k, str(v)) for k, v in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))]
    attacks = _attacks(held, names)
    short = _short_rows(approved, course_merges, professor_merges, aliases, names)
    tile_items = [(len(held), "held"), (pending_comments, _count_label(pending_comments, "comment")),
                  (pending_professors, _count_label(pending_professors, "professor")),
                  (pending_courses, _count_label(pending_courses, "course")),
                  (len(aliases), _count_label(len(aliases), "nickname"))]

    decided = Counter(decision_of(r) for r in held)
    # (count, label, bar color, legend color)
    agent_parts = [(len(approved), "approved", "#27ae60", "#27ae60"), (decided["reject"], "reject", "#e74c3c", "#e74c3c"),
                   (decided["escalate"], "escalated", "#f39c12", "#e08e0b"), (decided[None], "pending", "#cfcfd6", "#888")]
    checked = len(approved) + decided["reject"] + decided["escalate"]
    merges = len(course_merges) + len(professor_merges)
    agent_line = (f"Checked {_plural(checked, 'held rating')}"
                  + (f" and made {_plural(merges, 'merge')}" if merges else "") + ".")
    nums = [("New ratings", ratings["new"], "new", "#222"), ("Live ratings", ratings["live"], "live", "#27ae60"),
            ("Held ratings", ratings["held"], "held", "#e08e0b"),
            ("Rejected ratings", ratings["rejected"], "rejected", "#999")]
    totals = [("Live ratings, all time", f"{ratings['live_all']:,}"),
              ("Comments showing, all time", f"{ratings['comments_all']:,}")]

    needs = dh.tiles(tile_items) + dh.rows(reason_items, "Why they're waiting")
    if attacks:
        body = "".join(f"<div>{escape(s)}</div>{dh.command(c)}" for s, c in attacks)
        needs += dh.callout(f"Reject {_plural(len(attacks), 'attack')}", body)
    needs += dh.rows(short)
    if aliases:
        needs += dh.command("python review_ratings.py approve-alias ID")
    ratings_html = (
        f'<table {_TABLE}><tr valign="bottom"><td class="col" width="52%">'
        f'{dh.numbers([(n, short_label, c) for _, n, short_label, c in nums])}</td>'
        f'<td class="col col-chart" width="48%" style="padding-left:16px;">{dh.day_bars(ratings["days"])}</td>'
        f"</tr></table>" + dh.rows(totals))
    agent_html = (f'<div style="font-size:12px;color:#444;margin-bottom:8px;">{escape(agent_line)}</div>'
                  + dh.stacked_bar([(n, bar) for n, _, bar, _ in agent_parts])
                  + dh.legend([(n, label, legend) for n, label, _, legend in agent_parts]))
    sections = (dh.section("Needs you", needs, first=True) + dh.section("Ratings", ratings_html)
                + dh.section("Review agent", agent_html))
    if meters:
        meter_rows = "".join(dh.meter(m["label"], m["used"], m["limit"], _meter_shown(m)) if m.get("limit")
                             else dh.meter_note(m["note"]) for m in meters)
        sections += dh.section(
            "Usage limits",
            f'<table {_TABLE} style="font-size:12px;color:#444;">{meter_rows}</table>'
            f'<div style="font-size:11px;color:#999;margin-top:8px;line-height:1.5;">{_RATE_NOTE}</div>')
    footer = (f'Full queue: <span style="font-family:{_MONO};">python review_ratings.py list</span><br>'
              "No comment text, hashes or network data in this email.")
    html = dh.page(subject, dateline, sections, footer)

    text = [dateline, "", "Needs you"] + [f"{label.capitalize()}: {n}" for n, label in tile_items]
    if reason_items:
        text += ["", "Why they're waiting"] + [f"{k}: {v}" for k, v in reason_items]
    if attacks:
        text += ["", f"Reject {_plural(len(attacks), 'attack')}"] + [line for pair in attacks for line in pair]
    if short:
        text += [""] + [f"{label}: {value}" for label, value in short]
    if aliases:
        text += ["", "python review_ratings.py approve-alias ID"]
    text += ["", "Ratings"] + [f"{label}: {n}" for label, n, _, _ in nums] + [f"{k}: {v}" for k, v in totals]
    text += ["", "Review agent", agent_line] + [f"{label}: {n}" for n, label, _, _ in agent_parts]
    if meters:
        text += ["", "Usage limits"] + [f"{m['label']}: {_meter_shown(m)}" if m.get("limit") else m["note"]
                                        for m in meters]
    text += ["", "Full queue: python review_ratings.py list", "No comment text, hashes or network data in this email."]
    return subject, "\n".join(text), html


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
        comments = fetch_all(conn, "SELECT count(*) AS n, "
                                   "count(*) FILTER (WHERE comment_check = 'review') AS flagged, "
                                   "count(*) FILTER (WHERE comment_check IS DISTINCT FROM 'review' "
                                   "AND comment_check IS DISTINCT FROM 'allow') AS unchecked "
                                   "FROM survey_ratings WHERE comment_status = 'pending'")
        professors = fetch_all(conn, "SELECT count(*) AS n FROM survey_pending_professors WHERE status = 'pending'")
        courses = fetch_all(conn, "SELECT count(*) AS n FROM survey_pending_courses WHERE status = 'pending'")
        # The merge's reason ends "; N rating(s)": moving the ratings cleared their link to the course.
        merges = fetch_all(conn, "SELECT code, resolved_code, COALESCE(substring(agent_reason from '([0-9]+) rating')::int, 0) "
                                 "AS n FROM survey_pending_courses WHERE status = 'merged' AND agent_decision = 'merge' "
                                 "AND agent_reviewed_at >= now() - interval '1 day' ORDER BY agent_reviewed_at")
        # A professor merge's reason ends "; N rating(s), M held": M are held as unverified_pair.
        prof_merges = fetch_all(conn, "SELECT id::text AS id, resolved_slug, COALESCE(substring(agent_reason from '([0-9]+) rating')::int, 0) "
                                      "AS n, COALESCE(substring(agent_reason from '([0-9]+) held')::int, 0) AS held "
                                      "FROM survey_pending_professors WHERE status = 'merged' AND agent_decision = 'merge' "
                                      "AND agent_reviewed_at >= now() - interval '1 day' ORDER BY agent_reviewed_at")
        aliases = fetch_all(conn, "SELECT id, alias_key, slug, source FROM professor_aliases "
                                  "WHERE status = 'pending' ORDER BY id")
    finally:
        conn.close()
    if not (held or approved or professors[0]["n"] or courses[0]["n"] or merges or prof_merges or aliases
            or comments[0]["n"]):
        print("nothing to review")
        return 0
    subject, text, html = build_digest(held, approved, professors[0]["n"], courses[0]["n"],
                                       now or datetime.now(timezone.utc), merges, prof_merges, aliases,
                                       pending_comments=comments[0]["n"], flagged_comments=comments[0]["flagged"],
                                       unchecked_comments=comments[0]["unchecked"])
    if args.dry_run:
        print(f"{subject}\n\n{text}")
        return 0
    return 0 if notify.send_team_email(subject, text) else 1


if __name__ == "__main__":
    sys.exit(main())
