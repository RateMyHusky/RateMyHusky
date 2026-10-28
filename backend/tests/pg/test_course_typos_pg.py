"""course_typos.banner_candidates against the real Banner tables."""

import psycopg2.extras
import pytest

import course_typos
from tests.pg.pgutil import truncate


@pytest.fixture(autouse=True)
def clean(pg):
    truncate(pg, "banner_course_offerings", "banner_course_instructors", "course_catalog")


def seed(pg, codes, taught_by=None, taught=()):
    with pg.cursor() as cur:
        for code in codes:
            cur.execute(
                "INSERT INTO banner_course_offerings (subject_course, subject, course_title, first_term_code, "
                "last_term_code, last_term_label, terms_offered, pattern, fall_years, spring_years, summer_years, "
                "pattern_window_years, instructor_count) VALUES (%s, %s, %s, '202210', '202710', "
                "'Fall 2026', 1, 'Fall', 1, 0, 0, 5, 1)", (code, code[:4], f"Title {code}"))
        for code in taught:
            cur.execute(
                "INSERT INTO banner_course_instructors (subject_course, instructor_key, professor_slug, "
                "match_method, terms_taught, sections, first_term_code, last_term_code, last_term_label) "
                "VALUES (%s, %s, %s, 'exact', 1, 1, '202210', '202710', 'Fall 2026')", (code, taught_by, taught_by))
    pg.commit()


def candidates(pg, code, slug=None):
    def query(sql, params):
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    return [c["code"] for c in course_typos.banner_candidates(code, query, slug)]


def test_the_professors_courses_lead_and_the_rest_is_all_banner(pg):
    seed(pg, ["CS2500", "CS2502", "CS2510", "CS9999"], "jane-doe", ["CS2510"])
    assert candidates(pg, "CS2501", "jane-doe") == ["CS2510"]
    assert candidates(pg, "CS2501", "bob-lee") == ["CS2500", "CS2502", "CS2510"]
    assert candidates(pg, "CS2501") == ["CS2500", "CS2502", "CS2510"]


def test_a_banner_only_exact_code_comes_first(pg):
    seed(pg, ["BIOL5541", "BIOL5540", "BIOL5542"], "jane-doe", ["BIOL5542"])
    assert candidates(pg, "BIOL5541", "jane-doe") == ["BIOL5541", "BIOL5542"]
    assert candidates(pg, "BIOL5541") == ["BIOL5541", "BIOL5540", "BIOL5542"]


def test_at_most_five_by_code(pg):
    seed(pg, [f"CS250{i}" for i in range(1, 10)])
    assert candidates(pg, "CS2500") == [f"CS250{i}" for i in range(1, 6)]
