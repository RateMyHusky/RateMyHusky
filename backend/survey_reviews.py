"""Student reviews from /rate for the professor page, read live from survey_ratings.

One statement reads the professor's accepted ratings, newest first, so a rating
shows as soon as the professor's cached page is dropped, not at the weekly
pipeline run. `grade` is never selected: the form promises it only appears in
totals. The term shows next to a comment only when the professor taught at
least MIN_TERM_ENROLLMENT students in that course that term. Otherwise the year
shows only when they taught the course in two or more terms that year, since the
page's teaching history would turn a one-term year back into the term; else no
date. No exact date goes out either: it would pin the term the year is hiding.
"""

import rating_identity

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
    """The professor's accepted ratings with the Banner enrollment of the term they
    name, and how many terms of that term's year they taught the course."""
    return query(f"""
        SELECT r.id, r.course_code, r.term_label, r.rating, r.comment, r.created_at, r.updated_at,
               (SELECT SUM(bs.enrollment) {_TAUGHT}
                   AND bt.term_label = r.term_label) AS term_enrollment,
               (SELECT COUNT(DISTINCT bs.term_code) {_TAUGHT}
                   AND right(bt.term_label, 4) = right(r.term_label, 4)) AS terms_in_year
        FROM survey_ratings r
        WHERE r.professor_slug = %s AND r.status = 'accepted'
        ORDER BY r.updated_at DESC
    """, (slug,))


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
    """Comments a reader can see, before the MAX_SURVEY_REVIEWS cap."""
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
