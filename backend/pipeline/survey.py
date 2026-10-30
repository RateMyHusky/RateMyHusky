"""The 'survey' source: accepted student ratings as summary rows, and approved new courses.

Same three row kinds as summaries.py: professor (slug, ''), course ('', code),
professor x course (slug, code). Rating and hours are means rounded to two
places (hours from each bucket's midpoint); the rating distribution always has
keys "1"-"5"; grades count only when given. Difficulty is the mean of the
ratings that answered it (older ones didn't), and num_difficulty counts them
so the blend weights it by those alone; would-take-again is not asked, so it
stays None. A rating with no course code is on a pending course and counts
nowhere until a reviewer approves or merges the course: an invented code per
rating would otherwise move the professor's rating without ever tripping the
per-pair burst check.
"""

import os
import re
import sys
from datetime import timedelta

HOURS_MIDPOINTS = {"0-2": 1.0, "3-4": 3.5, "5-7": 6.0, "8-10": 9.0, "10+": 12.0}
# Unreviewed ratings in the last 7 days above which a professor's or course's week is
# held instead of published. A drip under the route's hourly and daily caps still
# lands ~200 a week on one professor, or more on a course spread over its instructors.
WEEKLY_SURGE_PROF = 40
WEEKLY_SURGE_COURSE = 120
WEEK = timedelta(days=7)
# stats_cache key: epoch seconds of the last run that published, where the next surge scan starts.
SURGE_CHECKED_KEY = "surge_checked_at"


def _mean(values):
    return round(sum(values) / len(values), 2) if values else None


def _row(slug, code, ratings):
    grades = {}
    difficulties = [r["difficulty"] for r in ratings if r["difficulty"] is not None]
    for r in ratings:
        if r["grade"]:
            grades[r["grade"]] = grades.get(r["grade"], 0) + 1
    return {
        "professor_slug": slug, "course_code": code, "source": "survey",
        "rating": _mean([r["rating"] for r in ratings]),
        "difficulty": _mean(difficulties),
        "would_take_again_pct": None,
        "num_ratings": len(ratings),
        "num_difficulty": len(difficulties),
        "num_comments": sum(1 for r in ratings if (r["comment"] or "").strip()),  # run.py and survey_reviews pass approved comments only
        "hours_per_week": _mean([HOURS_MIDPOINTS[r["hours"]] for r in ratings if r["hours"] in HOURS_MIDPOINTS]),
        "rating_distribution": {str(s): sum(1 for r in ratings if r["rating"] == s) for s in range(1, 6)},
        "grade_distribution": grades,
    }


def survey_rows(ratings):
    """Summary rows for accepted ratings with a professor. Pure."""
    by_slug, by_code, by_pair = {}, {}, {}
    for r in ratings:
        if not r["course_code"]:
            continue
        by_slug.setdefault(r["professor_slug"], []).append(r)
        by_code.setdefault(r["course_code"], []).append(r)
        by_pair.setdefault((r["professor_slug"], r["course_code"]), []).append(r)
    rows = [_row(slug, "", rs) for slug, rs in sorted(by_slug.items())]
    rows += [_row("", code, rs) for code, rs in sorted(by_code.items())]
    rows += [_row(slug, code, rs) for (slug, code), rs in sorted(by_pair.items())]
    return rows


def surge_ids(ratings, now, since=None):
    """Ids of the unreviewed ratings in any 7 days over a professor's or course's weekly limit. Pure.

    The scan covers the last 7 days, or back to `since` (the last run that published)
    when that is earlier, so a failed or skipped weekly run leaves no week unchecked.
    It reads updated_at, so a wave of edits to old ratings counts like new ones. A
    reviewer-approved rating keeps its hold_reasons, so it never counts again.
    """
    start = min(now - WEEK, since) if since else now - WEEK
    scanned = sorted((r for r in ratings if r["course_code"] and r["hold_reasons"] is None
                      and r["updated_at"] >= start), key=lambda r: r["updated_at"])
    by_slug, by_code = {}, {}
    for r in scanned:
        by_slug.setdefault(r["professor_slug"], []).append(r)
        by_code.setdefault(r["course_code"], []).append(r)
    ids = set()
    for groups, limit in ((by_slug, WEEKLY_SURGE_PROF), (by_code, WEEKLY_SURGE_COURSE)):
        for group in groups.values():
            first = 0
            for last, r in enumerate(group):
                while r["updated_at"] - group[first]["updated_at"] >= WEEK:
                    first += 1
                if last - first + 1 > limit:
                    ids.update(x["id"] for x in group[first:last + 1])
    return ids


def mark_surge_checked(conn, now):
    """Record `now` as the start of the next surge scan; call only after the read models are written."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO stats_cache (key, value) VALUES (%s, %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (SURGE_CHECKED_KEY, int(now.timestamp())))
    conn.commit()


def apply_surge_holds(conn, ids):
    """Hold the surge ratings for review; return how many were held."""
    if not ids:
        return 0
    with conn.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET status = 'held', hold_reasons = 'weekly_surge' "
                    "WHERE id::text = ANY(%s) AND status = 'accepted' AND hold_reasons IS NULL",
                    (sorted(ids),))
        held = cur.rowcount
    conn.commit()
    return held


def approved_courses(approved, catalog_courses):
    """catalog_courses-shaped rows for approved codes the catalog doesn't have yet. Pure."""
    # Imported here: the web server builds live survey rows from this module and
    # doesn't ship scraper/.
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "scraper"))
    from load_catalog import normalize_text
    known = {c["code"] for c in catalog_courses}
    out = []
    for a in approved:
        if a["code"] in known:
            continue
        known.add(a["code"])
        out.append({
            "code": a["code"], "name": a["name"], "department": None,
            "subject": re.match(r"[A-Za-z]*", a["code"]).group(0),
            "search_text": " ".join(filter(None, [normalize_text(a["code"]), normalize_text(a["name"])])),
            "is_placeholder": False,
        })
    return out
