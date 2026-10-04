"""Rate My Professors data for the professor page.

Every number this module returns was measured by RMP: the catalog's RMP
columns and the stored rmp_reviews rows. Blended numbers live in the payload's
`summary` (professor_full.py), never here.

Injectable `query` like professor_full.py, so tests run without a database.
"""

import moderation

# Grades a reviewer can pick that are not a grade.
_NOT_A_GRADE = {"", "N/A", "Not sure yet", "Rather not say"}


def stat(value, places):
    """A stored rating for display, or None. 0 is not a score on RMP's 1-5
    scales, and the catalog endpoints already serve it as null."""
    return round(float(value), places) if value else None


def pct(value):
    """A stored percentage for display, or None. Unlike the 1-5 scales, 0% is
    a real value; a missing one is already stored as NULL."""
    return round(float(value), 1) if value is not None else None


def fetch_reviews(name_key, query, sanitize):
    """The professor's stored RMP ratings, moderation filter applied."""
    rows = query(f"""
        SELECT course, course_code, quality, difficulty, date, tags, attendance, grade,
               textbook, online_class, comment
        FROM rmp_reviews WHERE name_key = %s{moderation.sql_filter()}
    """, (name_key,))
    return [{
        "course": str(r["course"] or ""),
        "courseCode": r.get("course_code"),
        "quality": int(r["quality"]) if r["quality"] else 0,
        "difficulty": int(r["difficulty"]) if r["difficulty"] else 0,
        "date": str(r["date"] or ""),
        "tags": str(r["tags"] or ""),
        "attendance": str(r["attendance"] or ""),
        "grade": str(r["grade"] or ""),
        "textbook": str(r["textbook"] or ""),
        "online_class": str(r["online_class"] or ""),
        "comment": sanitize(r["comment"]) if r["comment"] else "",
    } for r in rows]


def rating_distribution(reviews):
    counts = {str(s): 0 for s in range(1, 6)}
    for r in reviews:
        q = r.get("quality") or 0
        if 1 <= q <= 5:
            counts[str(int(round(q)))] += 1
    return counts


def grade_distribution(reviews):
    counts = {}
    for r in reviews:
        g = (r.get("grade") or "").strip()
        if g not in _NOT_A_GRADE:
            counts[g] = counts.get(g, 0) + 1
    return counts


def distribution(d):
    """A stored 1-5 distribution with every star present."""
    d = d or {}
    return {str(s): int(d.get(str(s), 0)) for s in range(1, 6)}


def build_section(row, professor_url, reviews):
    """The `sources.rmp` block from the professor's `rmp` source_summary row.

    Always the same keys. Without RMP ratings it is `available: False` with every
    number null, never one borrowed from another source.
    """
    row = row or {}
    num_ratings = int(row.get("num_ratings") or 0)
    rating = stat(row.get("rating"), 2)
    available = num_ratings > 0 and rating is not None
    return {
        "available": available,
        "rating": rating if available else None,
        "difficulty": stat(row.get("difficulty"), 2) if available else None,
        "wouldTakeAgainPct": pct(row.get("would_take_again_pct")) if available else None,
        "numRatings": num_ratings,
        "professorUrl": professor_url,
        "ratingDistribution": distribution(row.get("rating_distribution")),
        "gradeDistribution": dict(row.get("grade_distribution") or {}),
        "reviews": reviews,
    }
