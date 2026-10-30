"""The course page payload: /api/courses/<code> and render.py.

Two statements: the course (catalog details and NUpath in one row), then every
source_summary row for the code, with professor names and photos joined on.
Then Banner teaching history, guarded: course_history and banner_terms' labels.
"""

import logging

import rmp
import teaching_history

log = logging.getLogger(__name__)

# Recent Professors looks back exactly one year from the current term: a code
# minus 100 is the same term a year earlier (Fall 2026 202710 -> Fall 2025
# 202610). Strict, no widening: when nobody is recent the page falls back to
# Most-Rated.
RECENT_SPAN = 100
RECENT_MAX = 10


def build_catalog(course):
    return {"description": course["description"], "credits": course["credit_hours"],
            "prerequisites": course["prerequisites"], "corequisites": course["corequisites"],
            "nupath": list(course["nupath"] or [])}


def recent_cutoff(terms):
    """banner_terms rows -> the Recent Professors cutoff in the label_code
    scheme, or None when no label is readable. The current term is the
    earliest open one (Banner opens next term for registration months before
    it starts), else the newest; labels that don't parse are skipped."""
    readable = [(t["view_only"], teaching_history.label_code(t["label"])) for t in terms]
    readable = [(closed, c) for closed, c in readable if c]
    open_codes = [c for closed, c in readable if not closed]
    current = min(open_codes) if open_codes else max((c for _, c in readable), default=None)
    return current - RECENT_SPAN if current else None


def build_recent(instructors, professors, cutoff):
    """Instructors who taught the course at or after `cutoff`, newest first
    (instructors' order), one card per professor, with this course's rating
    and rating count, their catalog-wide would-take-again, and
    only their in-window terms; with none, they're left out. Unreadable
    labels (label_code None) never count as in-window.
    An unmatched instructor has no slug, so is one card per name, which is
    also how the page keys them."""
    rating = {p["slug"]: p["rating"] for p in professors}
    num_ratings = {p["slug"]: p["numRatings"] for p in professors}
    recent, seen = [], set()
    for i in instructors:
        terms = [t for t in i["recentTerms"] if (teaching_history.label_code(t) or 0) >= cutoff]
        key = i["slug"] or ("unmatched", i["name"])
        if not terms or key in seen:
            continue
        seen.add(key)
        recent.append({
            "slug": i["slug"], "name": i["name"], "imageUrl": i["imageUrl"],
            "focusX": i["focusX"], "focusY": i["focusY"],
            "rating": rating.get(i["slug"]),
            "terms": terms,
            # 0 for a professor with no reviews of this course; None unmatched.
            "numRatings": num_ratings.get(i["slug"], 0) if i["slug"] else None,
            "wouldTakeAgainPct": i["wouldTakeAgainPct"],
        })
    return recent[:RECENT_MAX]


def _history(code, query, query_one, history_for, professors):
    """(history, failed): course_history plus recentInstructors, or None. Banner
    decorates the page and never fails it, so any error reads as "no history"
    with failed True, which keeps the caller from caching the page.
    The cutoff and the instructors' terms are both in the label_code scheme:
    labels, not codes, which may be CPS/Law ones."""
    try:
        history = history_for(code, query, query_one)
        if history is None:
            return None, False
        cutoff = recent_cutoff(query("SELECT term_label AS label, view_only FROM banner_terms"))
        recent = build_recent(history["instructors"], professors, cutoff) if cutoff else []
        return {**history, "recentInstructors": recent}, False
    except Exception:
        log.exception("teaching history failed for course %s", code)
        return None, True


def build_course(code, query, query_one, history_for=teaching_history.course_history):
    course = query_one("""
        SELECT cc.code, cc.name, cc.department, k.description, k.credit_hours,
               k.prerequisites, k.corequisites,
               (SELECT array_agg(n.attribute ORDER BY n.attribute)
                FROM catalog_nupath n WHERE n.code = cc.code) AS nupath
        FROM course_catalog cc
        LEFT JOIN catalog_courses k ON k.code = cc.code
        WHERE cc.code = %s
    """, (code,))
    if not course:
        return None
    rows = query("""
        SELECT s.professor_slug, s.source, s.rating, s.difficulty, s.num_ratings,
               s.hours_per_week, p.name, p.image_url, p.focus_x, p.focus_y
        FROM source_summary s
        LEFT JOIN professors_catalog p ON p.slug = s.professor_slug
        WHERE s.course_code = %s
    """, (code,))
    own = {r["source"]: r for r in rows if r["professor_slug"] == ""}
    b = own.get("blend") or {}
    professors = [{
        "slug": r["professor_slug"], "name": r["name"], "imageUrl": r["image_url"],
        "focusX": r["focus_x"] if r["focus_x"] is not None else 50.0,
        "focusY": r["focus_y"] if r["focus_y"] is not None else 30.0,
        "rating": rmp.stat(r["rating"], 2), "difficulty": rmp.stat(r["difficulty"], 2),
        "numRatings": int(r["num_ratings"] or 0),
    } for r in rows if r["professor_slug"] and r["source"] == "blend" and r["name"] is not None]
    professors.sort(key=lambda p: (-p["numRatings"], p["name"]))
    history, history_failed = _history(code, query, query_one, history_for, professors)
    banner = {}
    for i in (history or {}).get("instructors", []):
        if i["slug"]:
            banner.setdefault(i["slug"], i)   # newest first: keep the first
    for p in professors:
        i = banner.get(p["slug"], {})
        p["lastTerm"], p["avgClassSize"] = i.get("lastTerm"), i.get("avgClassSize")
    payload = {
        "code": course["code"], "name": course["name"], "department": course["department"] or "",
        "catalog": build_catalog(course),
        "summary": {
            "rating": rmp.stat(b.get("rating"), 2), "difficulty": rmp.stat(b.get("difficulty"), 2),
            "numRatings": int(b.get("num_ratings") or 0), "hoursPerWeek": rmp.stat(b.get("hours_per_week"), 1),
            "bySource": {src: {"rating": rmp.stat(r["rating"], 2), "numRatings": int(r["num_ratings"] or 0)}
                         for src, r in own.items() if src != "blend"},
        },
        "professors": professors,
        "history": history,
    }
    if history_failed:
        payload["_historyFailed"] = True    # private: server.course_payload pops it
    return payload
