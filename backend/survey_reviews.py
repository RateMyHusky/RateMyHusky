"""Student ratings from /rate for the professor page, read live from survey_ratings.

One statement reads the professor's accepted ratings, newest first. Every one
counts in the page's numbers as soon as the professor's cached page is dropped,
not at the weekly pipeline run (live_summary_rows). A comment becomes a review
card only once a reviewer approves it (review_ratings.py approve-comment);
until then it shows nowhere and counts in no comment total. `grade` feeds only
the totals and never goes out with a comment: the form promises that. The term shows next to a comment only when the professor taught at
least MIN_TERM_ENROLLMENT students in that course that term. Otherwise the year
shows only when they taught the course in two or more terms that year, since the
page's teaching history would turn a one-term year back into the term; else no
date. No exact date goes out either: it would pin the term the year is hiding.
"""

import rating_identity
from pipeline import survey

MIN_TERM_ENROLLMENT = 15
MAX_SURVEY_REVIEWS = 200


def public_id(secret, rating_uuid):
    """A review's id on the page and in reports: keyed, so it can't be turned back
    into the row id (review_ratings.py remove-comment finds the row by it)."""
    return rating_identity.keyed_hash(secret, "review", str(rating_uuid))[:12]


_TAUGHT = """
                  FROM banner_sections bs
                  JOIN banner_terms bt ON bt.term_code = bs.term_code
                  JOIN banner_section_instructors bsi ON bsi.term_code = bs.term_code AND bsi.crn = bs.crn
                  JOIN banner_course_instructors bci ON bci.instructor_key = bsi.instructor_key
                                                    AND bci.subject_course = bs.subject_course
                 WHERE bci.professor_slug = r.professor_slug AND bs.subject_course = r.course_code"""


def fetch_rows(slug, query):
    """The professor's accepted ratings, each with its course's catalog name, the
    Banner enrollment of the term it names, and how many terms of that term's year
    the professor taught the course. `comment` is NULL unless a reviewer approved it."""
    return query(f"""
        SELECT r.id, r.professor_slug, r.course_code, c.name AS course_name, r.term_label,
               r.rating, r.difficulty, r.hours, r.grade,
               CASE WHEN r.comment_status = 'approved' THEN r.comment END AS comment,
               r.created_at, r.updated_at,
               (SELECT SUM(bs.enrollment) {_TAUGHT}
                   AND bt.term_label = r.term_label) AS term_enrollment,
               (SELECT COUNT(DISTINCT bs.term_code) {_TAUGHT}
                   AND right(bt.term_label, 4) = right(r.term_label, 4)) AS terms_in_year
        FROM survey_ratings r
        LEFT JOIN course_catalog c ON c.code = r.course_code
        WHERE r.professor_slug = %s AND r.status = 'accepted'
        ORDER BY r.updated_at DESC
    """, (slug,))


def live_summary_rows(rows):
    """The professor's `survey` source_summary rows, (slug, '') and one per course,
    built from fetch_rows the way the weekly pipeline builds them. A rating on a
    pending course has no course_code and counts nowhere, as in the pipeline.
    Each row carries its course's catalog name (None on the professor row)."""
    names = {r["course_code"]: r["course_name"] for r in rows}
    return [{**r, "course_name": names.get(r["course_code"])}
            for r in survey.survey_rows(rows) if r["professor_slug"]]


def when(term_label, enrollment, terms_in_year, created_at):
    """The term; in a small class its year, or "" when the year has only that term;
    the year written without a term."""
    if not term_label:
        return str(created_at.year)
    if enrollment is not None and enrollment >= MIN_TERM_ENROLLMENT:
        return term_label
    return term_label.rsplit(" ", 1)[-1] if (terms_in_year or 0) >= 2 else ""


def _shown(r):
    return bool((r["comment"] or "").strip())


def comment_count(rows):
    """Approved comments a reader can see, before the MAX_SURVEY_REVIEWS cap."""
    return sum(1 for r in rows if _shown(r))


def shape_reviews(rows, review_id, sanitize):
    """Review cards for the rows with a comment. `review_id(uuid)` gives the public
    id; without one (no RATING_SECRET) there are no cards."""
    if review_id is None:
        return []
    return [{
        "id": review_id(r["id"]),
        "course": r["course_code"],
        "when": when(r["term_label"], r["term_enrollment"], r["terms_in_year"], r["created_at"]),
        "rating": int(r["rating"]),
        "comment": sanitize(r["comment"]),
    } for r in rows if _shown(r)][:MAX_SURVEY_REVIEWS]
