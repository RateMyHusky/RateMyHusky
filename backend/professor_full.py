"""The professor page payload: /api/professors/<slug>/full and render.py.

Injectable `query`/`query_one` (the chat_retrieve.py pattern) so it is
unit-tested without a database. At most four statements: the catalog row, the
professor's source_summary rows, RMP reviews, Reddit.

`summary` is the only place blended numbers live; `sources.<name>` holds what
each source measured. A new source adds `sources.<name>` and
`summary.bySource.<name>` and nothing else.
"""

import moderation
import rmp
from prof_aliases import ALIAS_MAP


def _resolve_professor(slug, query_one):
    """One catalog lookup, slug then name_key fallback (alias-resolved)."""
    prof = query_one("SELECT * FROM professors_catalog WHERE slug = %s", (slug,))
    if not prof:
        name_key = slug.strip().lower().replace("-", " ")
        name_key = ALIAS_MAP.get(name_key, name_key)
        prof = query_one("SELECT * FROM professors_catalog WHERE name_key = %s", (name_key,))
    return prof


def build_identity(prof):
    return {
        "slug": prof["slug"],
        "name": prof["name"],
        "department": prof["department"],
        "college": prof.get("college"),
        "imageUrl": prof.get("image_url"),
        "focusX": prof.get("focus_x") if prof.get("focus_x") is not None else 50.0,
        "focusY": prof.get("focus_y") if prof.get("focus_y") is not None else 30.0,
    }


def build_summary(own_rows, reddit_mentions):
    """`own_rows`: {source: professor-level source_summary row}."""
    b = own_rows.get("blend") or {}
    return {
        "rating": rmp.stat(b.get("rating"), 2),
        "difficulty": rmp.stat(b.get("difficulty"), 2),
        "wouldTakeAgainPct": rmp.pct(b.get("would_take_again_pct")),
        "numRatings": int(b.get("num_ratings") or 0),
        "numComments": int(b.get("num_comments") or 0) + len(reddit_mentions),
        "hoursPerWeek": rmp.stat(b.get("hours_per_week"), 1),
        "bySource": {src: {"rating": rmp.stat(r.get("rating"), 2), "numRatings": int(r.get("num_ratings") or 0)}
                     for src, r in own_rows.items() if src != "blend"},
    }


def build_courses(course_rows):
    """One row per course the professor has ratings in, from the blend rows, most-rated first."""
    rows = [{
        "code": r["course_code"],
        "name": r["course_name"],
        "rating": rmp.stat(r["rating"], 2),
        "difficulty": rmp.stat(r["difficulty"], 2),
        "numRatings": int(r["num_ratings"] or 0),
        "ratingDistribution": rmp.distribution(r["rating_distribution"]),
    } for r in course_rows]
    rows.sort(key=lambda c: (-c["numRatings"], c["code"]))
    return rows


def build_payload(slug, query, query_one, sanitize, fetch_reddit_mentions):
    """The §4.2 professor payload, or None when no professor matches `slug`.
    Four statements: catalog row, summaries, RMP reviews, Reddit."""
    prof = _resolve_professor(slug, query_one)
    if not prof:
        return None
    summaries = query("""
        SELECT s.course_code, s.source, s.rating, s.difficulty, s.would_take_again_pct,
               s.num_ratings, s.num_comments, s.hours_per_week,
               s.rating_distribution, s.grade_distribution, c.name AS course_name
        FROM source_summary s
        LEFT JOIN course_catalog c ON c.code = s.course_code
        WHERE s.professor_slug = %s
    """, (prof["slug"],))
    own = {r["source"]: r for r in summaries if r["course_code"] == ""}
    reviews = rmp.fetch_reviews(prof["name_key"], query, sanitize)
    mentions = fetch_reddit_mentions(prof["slug"], query, moderation.sql_filter("t"))
    for m in mentions:
        m["body"] = sanitize(m["body"]) if m["body"] else ""
    return {
        "version": 2,
        "identity": build_identity(prof),
        "summary": build_summary(own, mentions),
        "sources": {"rmp": rmp.build_section(own.get("rmp"), prof.get("professor_url"), reviews)},
        "courses": build_courses([r for r in summaries if r["course_code"] and r["source"] == "blend"]),
        "redditMentions": mentions,
    }
