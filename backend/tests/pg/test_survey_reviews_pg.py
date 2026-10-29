"""survey_reviews.fetch_rows against real PostgreSQL: the accepted-only filter and
the term enrollment sum over Banner's tables."""

import uuid

import pytest

import survey_reviews
from tests.pg.pgutil import query_fn, truncate

SLUG = "olin-guha"


@pytest.fixture(autouse=True)
def clean(pg):
    truncate(pg, "survey_ratings", "banner_terms", "banner_sections", "banner_section_instructors",
             "banner_course_instructors")


def rating(cur, slug, comment, status="accepted", device=None):
    cur.execute(
        "INSERT INTO survey_ratings (id, professor_slug, course_code, term_label, rating, hours, grade, comment, "
        "status, device_hash, new_device, network_type) "
        "VALUES (%s, %s, 'PHIL2325', 'Fall 2025', 4, '3-4', 'A', %s, %s, %s, true, 'unknown')",
        (str(uuid.uuid4()), slug, comment, status, device or comment))


def section(cur, crn, instructor_key, enrollment):
    cur.execute(
        "INSERT INTO banner_sections (term_code, crn, subject_course, enrollment) VALUES ('202610', %s, 'PHIL2325', %s)",
        (crn, enrollment))
    cur.execute(
        "INSERT INTO banner_section_instructors (term_code, crn, instructor_key, instructor_name) "
        "VALUES ('202610', %s, %s, %s)", (crn, instructor_key, instructor_key))


def seed(pg):
    with pg.cursor() as cur:
        rating(cur, SLUG, "accepted")
        rating(cur, SLUG, "held", status="held")
        rating(cur, "someone-else", "other prof")
        cur.execute(
            "INSERT INTO banner_terms (term_code, term_label, season, season_group, year, view_only, "
            "scraped_closed, section_count, attributed_sections, instructor_count, instructors_source) "
            "VALUES ('202610', 'Fall 2025', 'Fall', 'Fall', 2025, false, true, 3, 3, 2, 'banner')")
        for key, slug in (("guha, olin", SLUG), ("doe, jane", "jane-doe")):
            cur.execute(
                "INSERT INTO banner_course_instructors (subject_course, instructor_key, professor_slug, match_method, "
                "terms_taught, sections, first_term_code, last_term_code, last_term_label) "
                "VALUES ('PHIL2325', %s, %s, 'exact', 1, 1, '202610', '202610', 'Fall 2025')", (key, slug))
        section(cur, "10001", "guha, olin", 9)
        section(cur, "10002", "guha, olin", 8)
        section(cur, "10003", "doe, jane", 100)
    pg.commit()


def test_fetch_rows_returns_accepted_rows_for_the_slug_with_their_term_enrollment(pg):
    seed(pg)
    rows = survey_reviews.fetch_rows(SLUG, query_fn(pg))
    assert [r["comment"] for r in rows] == ["accepted"]
    assert rows[0]["term_enrollment"] == 17   # 9 + 8; the other instructor's 100 is not counted
    assert "grade" not in rows[0]
    assert rows[0]["terms_in_year"] == 1


def test_terms_in_year_counts_the_professors_terms_of_that_course_that_year(pg):
    seed(pg)
    with pg.cursor() as cur:
        for code, label in (("202650", "Summer 1 2025"), ("202530", "Spring 2025"), ("202710", "Fall 2026")):
            cur.execute(
                "INSERT INTO banner_terms (term_code, term_label, season, season_group, year, view_only, "
                "scraped_closed, section_count, attributed_sections, instructor_count, instructors_source) "
                "VALUES (%s, %s, 'x', 'x', 2025, false, true, 1, 1, 1, 'banner')", (code, label))
        # Summer 1 2025 by this professor counts; Spring 2025 by someone else and Fall 2026 don't.
        for code, crn, key in (("202650", "20001", "guha, olin"), ("202530", "20002", "doe, jane"),
                               ("202710", "20003", "guha, olin")):
            cur.execute("INSERT INTO banner_sections (term_code, crn, subject_course, enrollment) "
                        "VALUES (%s, %s, 'PHIL2325', 5)", (code, crn))
            cur.execute("INSERT INTO banner_section_instructors (term_code, crn, instructor_key, instructor_name) "
                        "VALUES (%s, %s, %s, %s)", (code, crn, key, key))
    pg.commit()
    (row,) = survey_reviews.fetch_rows(SLUG, query_fn(pg))
    assert row["terms_in_year"] == 2
