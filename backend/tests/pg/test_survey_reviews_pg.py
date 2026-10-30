"""survey_reviews.fetch_rows against real PostgreSQL: the accepted-only filter and
the term enrollment sum over Banner's tables."""

import uuid

import pytest

import survey_reviews
from tests.pg.pgutil import query_fn, truncate

SLUG = "olin-guha"


@pytest.fixture(autouse=True)
def clean(pg):
    truncate(pg, "survey_ratings", "course_catalog", "banner_terms", "banner_sections",
             "banner_section_instructors", "banner_course_instructors")


def rating(cur, slug, comment, status="accepted", device=None, comment_status="approved"):
    cur.execute(
        "INSERT INTO survey_ratings (id, professor_slug, course_code, term_label, rating, hours, grade, comment, "
        "status, device_hash, new_device, network_type, comment_status) "
        "VALUES (%s, %s, 'PHIL2325', 'Fall 2025', 4, '3-4', 'A', %s, %s, %s, true, 'unknown', %s)",
        (str(uuid.uuid4()), slug, comment, status, device or comment, comment_status))


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
    assert rows[0]["terms_in_year"] == 1
    assert rows[0]["grade"] == "A"   # for the totals; shape_reviews never sends it


def test_a_comment_no_reviewer_approved_comes_back_null_but_its_rating_still_counts(pg):
    seed(pg)
    with pg.cursor() as cur:
        rating(cur, SLUG, "unread", comment_status="pending")
        cur.execute("INSERT INTO course_catalog (code, name) VALUES ('PHIL2325', 'Ethics')")
    pg.commit()
    rows = survey_reviews.fetch_rows(SLUG, query_fn(pg))
    assert sorted(r["comment"] or "" for r in rows) == ["", "accepted"]
    assert {r["course_name"] for r in rows} == {"Ethics"}
    (prof, course) = survey_reviews.live_summary_rows(rows)
    assert prof["num_ratings"] == 2 and prof["num_comments"] == 1
    assert survey_reviews.comment_count(rows) == 1


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


def test_the_page_numbers_are_live_and_only_approved_comments_show(pg):
    import json

    from professor_full import build_payload
    from tests.pg.pgutil import truncate as empty
    empty(pg, "professors_catalog", "source_summary", "rmp_reviews")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors_catalog (slug, name, name_key) VALUES (%s, 'Olin Guha', 'olin guha')",
                    (SLUG,))
        # Last week's run: RMP 10 at 3.0, and a survey row that no longer matches the table.
        for code, source, score, n in (("", "rmp", 3.0, 10), ("", "survey", 1.0, 7), ("", "blend", 2.4, 17),
                                        ("PHIL2325", "rmp", 3.0, 10)):
            cur.execute("INSERT INTO source_summary (professor_slug, course_code, source, rating, num_ratings, "
                        "rating_distribution) VALUES (%s, %s, %s, %s, %s, %s)",
                        (SLUG, code, source, score, n, json.dumps({"3": n})))
        rating(cur, SLUG, "shown")
        rating(cur, SLUG, "unread", comment_status="pending")
    pg.commit()

    def query_one(sql, params=None):
        return (query_fn(pg)(sql, params) or [None])[0]
    data = build_payload(SLUG, query_fn(pg), query_one, lambda t: t, lambda *a: [],
                         awards_for=lambda k: [], course_history_for=lambda s, q: [], review_id=lambda u: "id")
    assert [r["comment"] for r in data["sources"]["survey"]["reviews"]] == ["shown"]
    assert data["sources"]["survey"]["numRatings"] == 2 and data["sources"]["survey"]["rating"] == 4.0
    assert data["summary"]["numRatings"] == 12
    assert data["summary"]["rating"] == round((3.0 * 10 + 4.0 * 2) / 12, 2)
    assert data["summary"]["numComments"] == 1
    (course,) = data["courses"]
    assert course["code"] == "PHIL2325" and course["numRatings"] == 12
    assert course["ratingDistribution"]["4"] == 2
