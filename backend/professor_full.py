"""The professor page payload: /api/professors/<slug>/full and render.py.

Injectable `query`/`query_one` (the chat_retrieve.py pattern) so it is
unit-tested without a database. At most six statements: the catalog row, the
professor's source_summary rows, RMP reviews, Reddit, Banner teaching history,
then the live student reviews (survey_reviews.py).

`summary` is the only place blended numbers live; `sources.<name>` holds what
each source measured. A new source adds `sources.<name>` and
`summary.bySource.<name>` and nothing else.
"""

import logging

import psycopg2.errors

import moderation
import rmp
import survey_reviews
import teaching_awards
import teaching_history
from prof_aliases import ALIAS_MAP

log = logging.getLogger(__name__)


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


def build_survey_section(row, reviews=()):
    """The `sources.survey` block from the professor's `survey` source_summary row,
    plus `reviews`, the student comments read live (survey_reviews.shape_reviews).

    Always the same keys. Without survey ratings it is `available: False` with
    every number null, like `rmp.build_section`.
    """
    row = row or {}
    num_ratings = int(row.get("num_ratings") or 0)
    rating = rmp.stat(row.get("rating"), 2)
    available = num_ratings > 0 and rating is not None
    return {
        "available": available,
        "rating": rating if available else None,
        "numRatings": num_ratings,
        "hoursPerWeek": rmp.stat(row.get("hours_per_week"), 1) if available else None,
        "ratingDistribution": rmp.distribution(row.get("rating_distribution")),
        "gradeDistribution": dict(row.get("grade_distribution") or {}),
        "reviews": list(reviews),
    }


def build_summary(own_rows, reddit_mentions, survey_comments=None):
    """`own_rows`: {source: professor-level source_summary row}. `survey_comments`,
    the live count, replaces the survey row's count from the last pipeline run so
    the stat matches the RateMyHusky tab; None (reviews off) keeps the pipeline's."""
    b = own_rows.get("blend") or {}
    stale_survey = int((own_rows.get("survey") or {}).get("num_comments") or 0)
    if survey_comments is None:
        survey_comments = stale_survey
    return {
        "rating": rmp.stat(b.get("rating"), 2),
        "difficulty": rmp.stat(b.get("difficulty"), 2),
        "wouldTakeAgainPct": rmp.pct(b.get("would_take_again_pct")),
        "numRatings": int(b.get("num_ratings") or 0),
        "numComments": int(b.get("num_comments") or 0) - stale_survey + survey_comments + len(reddit_mentions),
        "hoursPerWeek": rmp.stat(b.get("hours_per_week"), 1),
        "bySource": {src: {"rating": rmp.stat(r.get("rating"), 2), "numRatings": int(r.get("num_ratings") or 0)}
                     for src, r in own_rows.items() if src != "blend"},
    }


def build_courses(course_rows, history):
    """Reviewed courses (the blend rows) merged on code with the courses Banner
    has them teaching. Taught courses come first in `history`'s order (most
    recently taught, then most terms); the rest follow most-rated first. A
    course Banner lists but no one has rated has no ratings. hasPage: the code
    is in course_catalog, so a course page exists."""
    reviewed = {r["course_code"]: {
        "code": r["course_code"],
        "name": r["course_name"],
        "rating": rmp.stat(r["rating"], 2),
        "difficulty": rmp.stat(r["difficulty"], 2),
        "numRatings": int(r["num_ratings"] or 0),
        "ratingDistribution": rmp.distribution(r["rating_distribution"]),
        "hasPage": r["course_name"] is not None,
    } for r in course_rows}
    taught = []
    seen = set()
    for h in history:
        if h["code"] in seen:   # a second Banner instructor key: the newest row wins
            continue
        seen.add(h["code"])
        row = reviewed.pop(h["code"], None) or {
            "code": h["code"], "name": h["name"], "rating": None, "difficulty": None,
            "numRatings": 0, "ratingDistribution": None, "hasPage": h["hasPage"]}
        taught.append({**row, "name": row["name"] or h["name"],   # Banner's title when the catalog has none
                       "terms": h["recentTerms"], "lastTerm": h["lastTerm"]})
    rest = sorted(reviewed.values(), key=lambda c: (-c["numRatings"], c["code"]))
    return taught + [{**c, "terms": [], "lastTerm": None} for c in rest]


def _course_history(slug, query, course_history_for):
    """(courses, failed): Banner's courses for the professor, or [] when they
    can't be read: history decorates the page and never fails it, and failed
    True keeps the caller from caching the page."""
    try:
        return course_history_for(slug, query), False
    except Exception:
        log.exception("teaching history failed for professor %s", slug)
        return [], True


def _survey(slug, query):
    """(rows, failed). A database without survey_ratings yet has no student
    reviews and nothing went wrong; any other failure, a missing Banner table
    included, leaves them out and sets failed so the page isn't cached."""
    try:
        return survey_reviews.fetch_rows(slug, query), False
    except psycopg2.errors.UndefinedTable as e:
        if '"survey_ratings"' in str(e):
            return [], False
        log.exception("student reviews failed for professor %s", slug)
        return [], True
    except Exception:
        log.exception("student reviews failed for professor %s", slug)
        return [], True


def build_payload(slug, query, query_one, sanitize, fetch_reddit_mentions,
                  awards_for=teaching_awards.awards_for,
                  course_history_for=teaching_history.professor_course_history,
                  review_id=None):
    """The §4.2 professor payload, or None when no professor matches `slug`.
    Six statements: catalog row, summaries, RMP reviews, Reddit, then Banner
    history and the student reviews last, so a failure there can't affect the
    reads before it. Awards come from the committed teaching_awards.json, not
    the database. `review_id(uuid)` gives a student review its public id; None
    (reviews off, or no RATING_SECRET) skips the survey read, so no review text
    or live count goes out."""
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
    history, history_failed = _course_history(prof["slug"], query, course_history_for)
    survey_rows, survey_failed = _survey(prof["slug"], query) if review_id else ([], False)
    payload = {
        "version": 2,
        "identity": build_identity(prof),
        "summary": build_summary(own, mentions, survey_reviews.comment_count(survey_rows) if review_id else None),
        "sources": {"rmp": rmp.build_section(own.get("rmp"), prof.get("professor_url"), reviews),
                    "survey": build_survey_section(
                        own.get("survey"), survey_reviews.shape_reviews(survey_rows, review_id, sanitize))},
        "courses": build_courses([r for r in summaries if r["course_code"] and r["source"] == "blend"],
                                 history),
        "lastTaught": history[0]["lastTerm"] if history else None,
        "redditMentions": mentions,
        "awards": awards_for(prof["name_key"]),
    }
    if history_failed or survey_failed:
        payload["_partial"] = True    # private: server.professor_payload pops it
    return payload
