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


def next_term(terms, current):
    """The first semester after the term in progress, as its label, or None. A
    CPS quarter (Winter) between the two is no semester and is skipped."""
    later = [(teaching_history.label_code(t["label"]), t["label"]) for t in terms
             if "Quarter" not in (t.get("track") or "")]
    later = [(c, label) for c, label in later if c and c > current]
    return min(later)[1] if later else None


def _card(i, by_slug):
    """One professor card: this course's rating and rating count (0 for a
    professor with no reviews of it, None unmatched), their catalog-wide
    would-take-again. `by_slug` is the course's professors keyed by slug."""
    p = by_slug.get(i["slug"], {})
    return {
        "slug": i["slug"], "name": i["name"], "imageUrl": i["imageUrl"],
        "focusX": i["focusX"], "focusY": i["focusY"],
        "rating": p.get("rating"),
        "numRatings": p.get("numRatings", 0) if i["slug"] else None,
        "wouldTakeAgainPct": i["wouldTakeAgainPct"],
    }


def build_recent(instructors, by_slug, cutoff, current):
    """Instructors who taught the course from `cutoff` through `current` (the
    term in progress), newest first (instructors'
    order), one card per professor with only their in-window terms; with none,
    they're left out. Unreadable labels (label_code None) never count as
    in-window.
    An unmatched instructor has no slug, so is one card per name, which is
    also how the page keys them."""
    recent, seen = [], set()
    for i in instructors:
        terms = [t for t in i["recentTerms"]
                 if cutoff <= (teaching_history.label_code(t) or 0) <= current]
        key = i["slug"] or ("unmatched", i["name"])
        if not terms or key in seen:
            continue
        seen.add(key)
        recent.append({**_card(i, by_slug), "terms": terms})
    return recent[:RECENT_MAX]


def build_next(instructors, by_slug, label):
    """Instructors Banner has teaching the course in `label`, one card each, in
    instructors' order. From 2026 a summer term's sections are labelled by
    session, so "Summer 2027" also takes "Summer 1 2027" and "Summer 2 2027"."""
    season, _, year = label.rpartition(" ")
    labels = {label, f"Summer 1 {year}", f"Summer 2 {year}"} if season == "Summer" else {label}
    out, seen = [], set()
    for i in instructors:
        key = i["slug"] or ("unmatched", i["name"])
        if labels & set(i["recentTerms"]) and key not in seen:
            seen.add(key)
            out.append(_card(i, by_slug))
    return out


def _history(code, query, query_one, history_for, professors):
    """(history, failed, current): course_history plus recentInstructors and next
    semester's (nextTerm, nextInstructors: None and [] when Banner lists no one
    for it yet), or None. lastOffered never names a term that hasn't started.
    Banner decorates the page and never fails it, so any error reads as "no
    history" with failed True, which keeps the caller from caching the page.
    The cutoff and the instructors' terms are both in the label_code scheme:
    labels, not codes, which may be CPS/Law ones. current is the term in
    progress (teaching_history.current_term_code), None with no history."""
    try:
        history = history_for(code, query, query_one)
        if history is None:
            return None, False, None
        terms = query(teaching_history.TERMS_SQL)
        current = teaching_history.current_term_code(terms)
        instructors = history["instructors"]
        by_slug = {p["slug"]: p for p in professors}
        recent = build_recent(instructors, by_slug, current - RECENT_SPAN, current) if current else []
        label = next_term(terms, current) if current else None
        upcoming = build_next(instructors, by_slug, label) if label else []
        last = history["lastOffered"]
        if current and (teaching_history.label_code(last) or 0) > current:
            last = teaching_history.latest_started([t for i in instructors for t in i["recentTerms"]], current)
        return {**history, "lastOffered": last, "recentInstructors": recent,
                "nextTerm": label if upcoming else None, "nextInstructors": upcoming}, False, current
    except Exception:
        log.exception("teaching history failed for course %s", code)
        return None, True, None


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
        "numRatings": int(r["num_ratings"] or 0), "hoursPerWeek": rmp.stat(r["hours_per_week"], 1),
    } for r in rows if r["professor_slug"] and r["source"] == "blend" and r["name"] is not None]
    professors.sort(key=lambda p: (-p["numRatings"], p["name"]))
    history, history_failed, current = _history(code, query, query_one, history_for, professors)
    banner = {}
    for i in (history or {}).get("instructors", []):
        if i["slug"]:
            banner.setdefault(i["slug"], i)   # newest first: keep the first
    for p in professors:
        i = banner.get(p["slug"], {})
        p["lastTerm"] = teaching_history.latest_started(i.get("recentTerms", []), current) if i else None
        p["avgClassSize"] = i.get("avgClassSize")
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
