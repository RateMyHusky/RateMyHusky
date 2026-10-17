"""The Banner loader and the teaching-history query against real PostgreSQL.

The scraper's own tests run the loader on sqlite; this runs the same write path
with a psycopg2 cursor, and runs the course-history query that selects the
offering_years / first_term_label columns the schema must carry.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scraper"))

import load_banner  # noqa: E402
import teaching_history  # noqa: E402
from tests.pg.pgutil import query_fn, rows, scalar, truncate  # noqa: E402

BANNER_TABLES = ("banner_terms", "banner_sections", "banner_section_instructors",
                 "banner_roster_duplicates", "banner_course_offerings",
                 "banner_course_instructors", "course_catalog", "professors_catalog")

FALL = {"label": "Fall 2026", "season": "Fall", "season_group": "Fall",
        "year": 2026, "track": "Semester", "view_only": False}


def section(crn, part_of_term="Full Term"):
    return {"crn": crn, "subject": "ACCT", "subject_course": "ACCT1201",
            "course_number": "1201", "section": "01", "course_title": "Accounting",
            "campus": "Boston", "instructional_method": "Traditional",
            "schedule_type": "Lecture", "credit_hours_low": 4.0,
            "credit_hours_high": 4.0, "enrollment": 30, "part_of_term": part_of_term}


def instructor(crn, key="annie witte"):
    return {"term_code": "202710", "crn": crn, "instructor_key": key,
            "instructor_name": "Witte, Annie", "is_primary": True}


def scrape(sections, instructors):
    return {"sections": sections, "instructors": instructors,
            "stats": {"section_count": len(sections),
                      "attributed_sections": len({i["crn"] for i in instructors}),
                      "instructor_count": len({i["instructor_key"] for i in instructors})}}


def test_write_term_lands_rows_and_a_rewrite_replaces_them(pg):
    truncate(pg, *BANNER_TABLES)
    cur = pg.cursor()
    first = scrape([section("1"), section("2", "Summer 1")], [instructor("1"), instructor("2")])
    assert load_banner.write_term(cur, "202710", FALL, "Fall 2026 Semester", first) == (2, 2)
    pg.commit()

    assert scalar(pg, "SELECT count(*) FROM banner_terms WHERE term_code = '202710'") == 1
    assert {r["crn"]: r["part_of_term"] for r in rows(
        pg, "SELECT crn, part_of_term FROM banner_sections")} == {"1": "Full Term", "2": "Summer 1"}
    assert scalar(pg, "SELECT count(*) FROM banner_section_instructors") == 2
    term = rows(pg, "SELECT term_label, view_only, section_count, instructors_source, "
                    "first_seen_at FROM banner_terms")[0]
    assert (term["term_label"], term["view_only"], term["section_count"],
            term["instructors_source"]) == ("Fall 2026", False, 2, "banner")
    assert term["first_seen_at"] is not None

    second = scrape([section("1")], [instructor("1", "patrick hurley")])
    assert load_banner.write_term(cur, "202710", FALL, "Fall 2026 Semester", second) == (1, 1)
    pg.commit()

    assert [r["crn"] for r in rows(pg, "SELECT crn FROM banner_sections")] == ["1"]
    assert [r["instructor_key"] for r in rows(
        pg, "SELECT instructor_key FROM banner_section_instructors")] == ["patrick hurley"]
    assert scalar(pg, "SELECT count(*) FROM banner_terms") == 1


def test_add_columns_is_a_no_op_when_the_schema_already_has_them(pg):
    cur = pg.cursor()
    load_banner.add_columns(cur, load_banner.ADDED_COLUMNS)
    load_banner.add_columns(cur, load_banner.ADDED_COLUMNS)
    pg.commit()
    assert scalar(pg, "SELECT count(*) FROM information_schema.columns WHERE "
                      "table_name = 'banner_sections' AND column_name = 'part_of_term'") == 1


def test_course_history_reads_the_offering_year_columns(pg):
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        cur.execute("""
            INSERT INTO banner_course_offerings
                (subject_course, subject, course_title, first_term_code, last_term_code,
                 last_term_label, terms_offered, pattern, fall_years, spring_years,
                 summer_years, pattern_window_years, instructor_count,
                 first_term_label, offering_years)
            VALUES ('ACCT1201', 'ACCT', 'Accounting', '202210', '202710', 'Fall 2026',
                    8, 'Fall and Spring', 4, 4, 3, 5, 1, 'Fall 2021', %s)""",
                (json.dumps({"window": [2025, 2026], "Fall": [2025, 2026], "Spring": [2026],
                             "Summer 1": [2025], "Summer 2": [], "Summer": [2025]}),))
        cur.execute("""
            INSERT INTO banner_course_instructors
                (subject_course, instructor_key, instructor_name, professor_slug, match_method,
                 terms_taught, sections, first_term_code, last_term_code, last_term_label)
            VALUES ('ACCT1201', 'annie witte', 'Witte, Annie', 'annie-witte', 'exact',
                    5, 9, '202210', '202710', 'Fall 2026')""")
        cur.execute("INSERT INTO course_catalog (code, name) VALUES ('ACCT1201', 'Accounting')")
        cur.execute("INSERT INTO professors_catalog (slug, name, name_key) "
                    "VALUES ('annie-witte', 'Annie Witte', 'annie witte')")
    pg.commit()

    query = query_fn(pg)
    query_one = lambda sql, params=None: next(iter(query(sql, params)), None)  # noqa: E731
    history = teaching_history.course_history("ACCT1201", query, query_one)

    assert history["offeringYears"] == {"window": [2025, 2026], "first": 2022,
                                        "fall": [2025, 2026], "spring": [2026],
                                        "summer1": [2025], "summer2": [], "summer": [2025]}
    assert history["firstOffered"] == "Fall 2021"
    assert [i["slug"] for i in history["instructors"]] == ["annie-witte"]
