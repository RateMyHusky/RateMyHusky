"""The Banner loader and the teaching-history query against real PostgreSQL.

The scraper's own tests run the loader on sqlite; this runs the same write path
with a psycopg2 cursor, and runs the course-history query that selects the
offering_years / first_term_label columns the schema must carry.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "scraper"))

import load_banner  # noqa: E402
import teaching_history  # noqa: E402
from banner_history import MAX_COURSES_PER_TERM  # noqa: E402
from pipeline import banner_roster  # noqa: E402
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


def _term(cur, code, track):
    cur.execute("INSERT INTO banner_terms (term_code, term_label, season, season_group, year, "
                "view_only, scraped_closed, section_count, attributed_sections, instructor_count, "
                "instructors_source, track) VALUES (%s, %s, 'Fall', 'Fall', 2025, true, true, "
                "0, 0, 0, 'banner', %s)", (code, f"Fall 2025 {track}", track))


def _taught(cur, term, crn, course, *keys, enrollment=20):
    cur.execute("INSERT INTO banner_sections (term_code, crn, subject, subject_course, "
                "schedule_type, enrollment) VALUES (%s, %s, %s, %s, 'Lecture', %s)",
                (term, crn, course[:-4], course, enrollment))
    for key in keys:
        cur.execute("INSERT INTO banner_section_instructors (term_code, crn, instructor_key, "
                    "instructor_name) VALUES (%s, %s, %s, %s)", (term, crn, key, key.title()))


def _course_instructor(cur, course, key, slug, keys):
    cur.execute("INSERT INTO banner_course_instructors (subject_course, instructor_key, "
                "professor_slug, match_method, terms_taught, sections, first_term_code, "
                "last_term_code, last_term_label, instructor_keys) VALUES "
                "(%s, %s, %s, 'alias', 1, 1, '202610', '202610', 'Fall 2025', %s)",
                (course, key, slug, keys))


def test_track_sections_reach_the_row_an_older_spelling_was_merged_into(pg):
    # The reviewer's case: 8 Law sections as "williams tom", 1 as "williams thomas"
    # (the spelling the row kept), 3 Semester sections elsewhere. Joined on the kept
    # key alone, Semester won 3 to 1 and the professor stayed out of Law.
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        _term(cur, "202614", "Law Semester")
        _term(cur, "202610", "Semester")
        for crn in range(8):
            _taught(cur, "202614", str(crn), "LAW7000", "williams tom")
        # Listed under both spellings: still one section.
        _taught(cur, "202614", "8", "LAW7000", "williams thomas", "williams tom")
        for crn in range(3):
            _taught(cur, "202610", str(crn), "CRIM3000", "williams thomas")
        _course_instructor(cur, "LAW7000", "williams thomas", "thomas-williams",
                           "williams thomas|williams tom")
        _course_instructor(cur, "CRIM3000", "williams thomas", "thomas-williams",
                           "williams thomas")
    pg.commit()

    got = banner_roster.split_cps_vote(rows(pg, banner_roster.TRACK_SECTIONS_SQL))[0]
    assert sorted((r["instructor_key"], r["professor_slug"], r["track"], r["sections"])
                  for r in got) == [(None, "thomas-williams", "Law Semester", 9),
                                    (None, "thomas-williams", "Semester", 3)]
    assert banner_roster.track_colleges(got, {}) == {"thomas-williams": "Law"}


def test_track_sections_fall_back_to_the_key_before_instructor_keys_is_written(pg):
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        _term(cur, "202614", "Law Semester")
        _taught(cur, "202614", "1", "LAW7000", "lucia nunez")
        _course_instructor(cur, "LAW7000", "lucia nunez", None, None)
    pg.commit()
    got = banner_roster.split_cps_vote(rows(pg, banner_roster.TRACK_SECTIONS_SQL))[0]
    assert [(r["instructor_key"], r["professor_slug"], r["sections"]) for r in got] == [("lucia nunez", None, 1)]


def test_a_cancelled_section_still_makes_a_coordinator(pg):
    # banner_history.roster_artifacts counts courses before cancelled sections go,
    # so a term with one too many courses, one of them cancelled, is not teaching.
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        _term(cur, "202614", "Law Semester")
        for n in range(MAX_COURSES_PER_TERM + 1):
            course = f"LAW{7000 + n}"
            _taught(cur, "202614", str(n), course, "jo coord", enrollment=0 if n == 0 else 20)
            _course_instructor(cur, course, "jo coord", "jo-coord", "jo coord")
    pg.commit()
    assert banner_roster.split_cps_vote(rows(pg, banner_roster.TRACK_SECTIONS_SQL))[0] == []


def test_a_law_course_in_a_semester_term_counts_as_law(pg):
    # From Fall 2025 Law courses run in the university's Semester terms.
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        _term(cur, "202610", "Semester")
        _taught(cur, "202610", "1", "LAW7000", "ada park")
        _taught(cur, "202610", "2", "LAW7001", "ada park")
        _taught(cur, "202610", "3", "CRIM3000", "ada park")
        for course in ("LAW7000", "LAW7001", "CRIM3000"):
            _course_instructor(cur, course, "ada park", "ada-park", "ada park")
    pg.commit()
    got = banner_roster.split_cps_vote(rows(pg, banner_roster.TRACK_SECTIONS_SQL))[0]
    assert sorted((r["track"], r["sections"]) for r in got) == [("Law Semester", 2), ("Semester", 1)]
    assert banner_roster.track_colleges(got, {}) == {"ada-park": "Law"}


def test_a_cps_subject_in_a_semester_term_counts_as_cps_quarter(pg):
    # Graduate CPS moves to Semester terms from Fall 2026 with renumbered courses
    # (PJM6100), so a subject mostly taught in CPS Quarter terms stands in.
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        _term(cur, "202655", "CPS Quarter")
        _term(cur, "202630", "Semester")
        _term(cur, "202710", "Semester")
        _taught(cur, "202655", "1", "PJM5900", "old hand")
        _taught(cur, "202655", "2", "PJM5901", "old hand")
        _taught(cur, "202630", "3", "PJM5902", "old hand")   # PJM: 2 of 3 in CPS Quarter
        _taught(cur, "202630", "4", "CHEM1211", "old hand")  # CHEM: never in CPS Quarter
        _taught(cur, "202710", "5", "PJM6100", "new hire")
        _taught(cur, "202710", "6", "CHEM1212", "chemist")
        for course, key in (("PJM5900", "old hand"), ("PJM5901", "old hand"), ("PJM5902", "old hand"),
                            ("CHEM1211", "old hand"), ("PJM6100", "new hire"), ("CHEM1212", "chemist")):
            _course_instructor(cur, course, key, key.replace(" ", "-"), key)
    pg.commit()
    got = banner_roster.split_cps_vote(rows(pg, banner_roster.TRACK_SECTIONS_SQL))[0]
    assert sorted((r["professor_slug"], r["track"], r["sections"]) for r in got) == [
        ("chemist", "After CPS Quarter", 1), ("new-hire", "CPS Quarter", 1),
        ("old-hand", "CPS Quarter", 3), ("old-hand", "Semester", 1)]
    assert banner_roster.track_colleges(got, {}) == {
        "new-hire": "Professional Studies", "old-hand": "Professional Studies"}
    assert banner_roster.split_cps_vote(rows(pg, banner_roster.TRACK_SECTIONS_SQL))[1] == {"PJM"}


def test_the_cps_vote_skips_sections_that_are_not_teaching(pg):
    # Cancelled and non-teaching CPS Quarter sections would carry XYZ over half;
    # they don't count as teaching anywhere else in the query, so not in the vote.
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        _term(cur, "202655", "CPS Quarter")
        _term(cur, "202630", "Semester")
        _taught(cur, "202655", "1", "XYZ5000", "adjunct", enrollment=0)
        _taught(cur, "202655", "2", "XYZ5001", "adjunct", enrollment=0)
        _taught(cur, "202655", "3", "XYZ5002", "adjunct")
        cur.execute("UPDATE banner_sections SET schedule_type = 'Coop Placement' WHERE crn = '3'")
        _taught(cur, "202630", "4", "XYZ5003", "day prof")
        _taught(cur, "202630", "5", "XYZ5004", "day prof")
        for course in ("XYZ5003", "XYZ5004"):
            _course_instructor(cur, course, "day prof", "day-prof", "day prof")
    pg.commit()
    got, voted = banner_roster.split_cps_vote(rows(pg, banner_roster.TRACK_SECTIONS_SQL))
    assert voted == frozenset()
    assert [(r["professor_slug"], r["track"], r["sections"]) for r in got] == [("day-prof", "Semester", 2)]


def test_a_graduate_catalog_cps_section_counts_as_cps_quarter(pg):
    # AAI never ran in a CPS Quarter term, so the vote can't find it; the catalog
    # files it under CPS. CHM is CPS too, but undergraduate, and stays Semester.
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        _term(cur, "202655", "CPS Quarter")
        _term(cur, "202710", "Semester")
        _taught(cur, "202710", "1", "AAI6600", "ai teacher")
        _taught(cur, "202710", "2", "CHM1211", "chemist")
        _course_instructor(cur, "AAI6600", "ai teacher", "ai-teacher", "ai teacher")
        _course_instructor(cur, "CHM1211", "chemist", "chemist", "chemist")
    pg.commit()
    got = banner_roster.split_cps_vote(rows(pg, banner_roster.TRACK_SECTIONS_SQL))[0]
    assert sorted((r["professor_slug"], r["track"]) for r in got) == [
        ("ai-teacher", "CPS Quarter"), ("chemist", "After CPS Quarter")]


def test_an_undergraduate_cps_subject_on_the_cps_semester_calendar_is_not_voted(pg):
    # CHM ran on CPS Semester, not CPS Quarter: the vote must not relabel it and
    # pull day-college chemists (the Toher case) into Professional Studies.
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        _term(cur, "202655", "CPS Quarter")
        _term(cur, "202535", "CPS Semester")
        _taught(cur, "202535", "1", "CHM1211", "chemist")
        _taught(cur, "202535", "2", "CHM1212", "chemist")
        _taught(cur, "202655", "3", "CHM1213", "chemist")
        for course in ("CHM1211", "CHM1212", "CHM1213"):
            _course_instructor(cur, course, "chemist", "chemist", "chemist")
    pg.commit()
    got, voted = banner_roster.split_cps_vote(rows(pg, banner_roster.TRACK_SECTIONS_SQL))
    assert voted == frozenset()
    assert sorted((r["track"], r["sections"]) for r in got) == [("CPS Quarter", 1), ("CPS Semester", 2)]


def test_a_semester_after_the_last_quarter_does_not_tip_a_cps_professor_out(pg):
    # Graduate CPS moved to Semester from Fall 2026 (202710). Counted in the
    # majority, those sections would take a CPS adjunct out of Professional Studies.
    # MATH, not a CPS subject: one PJM section is under the vote's bar.
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        _term(cur, "202655", "CPS Quarter")
        _term(cur, "202710", "Semester")
        _taught(cur, "202655", "1", "PJM5900", "adjunct")
        _taught(cur, "202710", "2", "MATH6000", "adjunct")
        _taught(cur, "202710", "3", "MATH6100", "adjunct")
        for course in ("PJM5900", "MATH6000", "MATH6100"):
            _course_instructor(cur, course, "adjunct", "adjunct", "adjunct")
    pg.commit()
    got = banner_roster.split_cps_vote(rows(pg, banner_roster.TRACK_SECTIONS_SQL))[0]
    assert sorted((r["track"], r["sections"]) for r in got) == [("After CPS Quarter", 2), ("CPS Quarter", 1)]
    assert banner_roster.track_colleges(got, {}) == {"adjunct": "Professional Studies"}


def test_a_later_cps_quarter_term_does_not_move_the_vote_cutoff(pg):
    # Banner lists a 202715 "Fall 2026 CPS Quarter" sibling. Read from the data,
    # the cutoff would move past 202710 and the renumbered PJM sections there
    # would dilute PJM under the bar.
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        _term(cur, "202655", "CPS Quarter")
        _term(cur, "202710", "Semester")
        _term(cur, "202715", "CPS Quarter")
        # Below 5000, so only the vote sends PJM to CPS Quarter.
        _taught(cur, "202655", "1", "PJM1900", "adjunct")
        for crn, course in (("2", "PJM4100"), ("3", "PJM4110")):
            _taught(cur, "202710", crn, course, "adjunct")
        _taught(cur, "202715", "4", "XYZ1000", "adjunct")
        _taught(cur, "202710", "5", "XYZ2000", "adjunct")
        for course in ("PJM1900", "PJM4100", "PJM4110", "XYZ1000", "XYZ2000"):
            _course_instructor(cur, course, "adjunct", "adjunct", "adjunct")
    pg.commit()
    got = rows(pg, banner_roster.TRACK_SECTIONS_SQL)
    track_rows, voted = banner_roster.split_cps_vote(got)
    assert voted == {"PJM"}
    assert banner_roster.cps_vote_near_bar(got) == {}
    # Nor the track cutoff: the 202710 and 202715 XYZ sections stay out of the majority.
    assert {r["track"]: r["sections"] for r in track_rows} == {
        "CPS Quarter": 3, banner_roster.AFTER_CPS_QUARTER: 2}


def test_a_course_number_past_int_range_does_not_abort_the_track_query(pg):
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        _term(cur, "202630", "Semester")
        # _taught takes the subject as all but the last 4 characters. Each of
        # these is graduate: past int range, 5 digits from 1, and lowercase.
        courses = ("MGT99999999999", "MGT10000", "mgt6100")
        for crn, course in enumerate(courses, 1):
            cur.execute("INSERT INTO banner_sections (term_code, crn, subject, subject_course, "
                        "schedule_type, enrollment) VALUES ('202630', %s, 'MGT', %s, 'Lecture', 20)",
                        (str(crn), course))
            cur.execute("INSERT INTO banner_section_instructors (term_code, crn, instructor_key, "
                        "instructor_name) VALUES ('202630', %s, 'adjunct', 'Adjunct')", (str(crn),))
        _taught(cur, "202630", "9", "MGT4100", "adjunct")
        for course in (*courses, "MGT4100"):
            _course_instructor(cur, course, "adjunct", "adjunct", "adjunct")
    pg.commit()
    track_rows, _ = banner_roster.split_cps_vote(rows(pg, banner_roster.TRACK_SECTIONS_SQL))
    assert {r["track"]: r["sections"] for r in track_rows} == {"CPS Quarter": 3, "Semester": 1}


def test_the_vote_reports_a_subject_close_to_the_bar(pg):
    # ITC clears the bar at 58% on production: 4 of 7 here.
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        _term(cur, "202655", "CPS Quarter")
        _term(cur, "202630", "Semester")
        for n in range(7):
            _taught(cur, "202655" if n < 4 else "202630", str(n), f"ITC{5000 + n}", "adjunct")
    pg.commit()
    assert banner_roster.cps_vote_near_bar(rows(pg, banner_roster.TRACK_SECTIONS_SQL)) == {
        "ITC": pytest.approx(4 / 7)}


def test_a_cps_section_in_a_law_semester_term_stays_law_semester(pg):
    # LST is a graduate catalog CPS subject; taught in a Law Semester term it is Law's.
    truncate(pg, *BANNER_TABLES)
    with pg.cursor() as cur:
        _term(cur, "202655", "CPS Quarter")
        _term(cur, "202514", "Law Semester")
        _taught(cur, "202514", "1", "LST6000", "law prof")
        _course_instructor(cur, "LST6000", "law prof", "law-prof", "law prof")
    pg.commit()
    got = banner_roster.split_cps_vote(rows(pg, banner_roster.TRACK_SECTIONS_SQL))[0]
    assert [(r["track"], r["sections"]) for r in got] == [("Law Semester", 1)]
