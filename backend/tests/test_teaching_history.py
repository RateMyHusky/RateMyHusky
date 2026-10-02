"""Banner-derived teaching history for course and professor pages.

The DB is stubbed by keying on the SQL text, as in test_course_api.py.
"""

from datetime import datetime, timedelta, timezone

import teaching_history as th

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)

OFFERING = {
    "subject_course": "CS3100", "course_title": "Program Design and Implementation 2",
    "last_term_label": "Fall 2026", "pattern": "Fall and Spring",
    "fall_years": 1, "spring_years": 1, "summer_years": 0, "pattern_window_years": 1,
    "median_section_size": 98.0, "credit_hours": "4", "instructor_count": 8,
    "offered_now": "Fall 2026",
}

INSTRUCTORS = [
    {"instructor_name": "Nunez, Lucia", "professor_slug": "lucia-nunez", "catalog_name": "Lucia Nunez",
     "terms_taught": 3, "last_term_label": "Fall 2026",
     "recent_terms": "Fall 2026,Spring 2026,Fall 2025", "avg_enrollment": 111.06},
    {"instructor_name": "Doe, Jane Q", "professor_slug": None, "catalog_name": None,
     "terms_taught": 1, "last_term_label": "Spring 2026",
     "recent_terms": "Spring 2026", "avg_enrollment": None},
]


def stub(one=None, many=None):
    seen = []

    def query_one(sql, params=()):
        seen.append((sql, params))
        return (one or (lambda s, p: None))(sql, params)

    def query(sql, params=()):
        seen.append((sql, params))
        return (many or (lambda s, p: []))(sql, params)

    return query, query_one, seen


def course_db(offerings=None, catalog=(), instructors=INSTRUCTORS):
    offerings = {"CS3100": OFFERING} if offerings is None else offerings

    def one(sql, params):
        if "FROM banner_course_offerings" in sql:
            return offerings.get(params[0])
        if "FROM course_catalog" in sql:
            return {"name": "x"} if params[0] in catalog else None
        raise AssertionError(sql)

    def many(sql, params):
        if "FROM banner_course_instructors" in sql:
            return instructors if params[0] in offerings else []
        raise AssertionError(sql)

    return stub(one, many)


# ── course history ──────────────────────────────────────────────────────

def test_course_history_summary():
    query, query_one, _ = course_db()
    got = th.course_history("CS3100", query, query_one)
    assert got["pattern"] == "Fall and Spring"
    assert got["seasonYears"] == {"fall": 1, "spring": 1, "summer": 0}
    assert got["windowYears"] == 1
    assert got["lastOffered"] == "Fall 2026"
    assert got["offeredNow"] == ["Fall 2026"]
    assert got["creditHours"] == "4"
    assert got["typicalClassSize"] == 98
    assert got["instructorCount"] == 8


def test_course_history_instructors_link_matched_and_name_the_rest():
    query, query_one, _ = course_db()
    got = th.course_history("CS3100", query, query_one)["instructors"]
    assert got[0] == {"name": "Lucia Nunez", "slug": "lucia-nunez", "termsTaught": 3,
                      "lastTerm": "Fall 2026",
                      "recentTerms": ["Fall 2026", "Spring 2026", "Fall 2025"],
                      "avgClassSize": 111}
    assert got[1]["name"] == "Jane Q Doe"
    assert got[1]["slug"] is None
    assert got[1]["avgClassSize"] is None


def test_course_history_is_none_without_banner_data():
    query, query_one, _ = course_db(offerings={})
    assert th.course_history("ZZZ1000", query, query_one) is None


def test_offered_now_empty_when_not_on_the_schedule():
    query, query_one, _ = course_db(offerings={"CS3100": {**OFFERING, "offered_now": None}})
    assert th.course_history("CS3100", query, query_one)["offeredNow"] == []


def test_successor_links_both_ways():
    old = {**OFFERING, "subject_course": "CS3500", "course_title": "Object-Oriented Design",
           "offered_now": None}
    query, query_one, _ = course_db(offerings={"CS3100": OFFERING, "CS3500": old},
                                    catalog={"CS3500"})
    new_page = th.course_history("CS3100", query, query_one)
    assert new_page["replaces"] == {"code": "CS3500", "name": "Object-Oriented Design",
                                    "since": "Fall 2025", "hasPage": True}
    assert new_page["replacedBy"] is None
    old_page = th.course_history("CS3500", query, query_one)
    assert old_page["replacedBy"] == {"code": "CS3100",
                                      "name": "Program Design and Implementation 2",
                                      "since": "Fall 2025", "hasPage": False}


def test_successor_link_alone_still_yields_history():
    """A retired code with no Banner rows of its own still points forward."""
    query, query_one, _ = course_db(offerings={"CS3100": OFFERING})
    got = th.course_history("CS3500", query, query_one)
    assert got["replacedBy"]["code"] == "CS3100"
    assert got["pattern"] is None
    assert got["instructors"] == []


def test_successors_are_khourys_published_mapping():
    assert th.COURSE_SUCCESSORS == {
        "CS2500": ("CS2000", "Fall 2025"),
        "CS2510": ("CS2100", "Fall 2025"),
        "CS3500": ("CS3100", "Fall 2025"),
    }


# ── professor course history ────────────────────────────────────────────

PROF_ROWS = [
    {"subject_course": "CS3100", "course_title": "Program Design and Implementation 2",
     "terms_taught": 3, "last_term_label": "Fall 2026",
     "recent_terms": "Fall 2026,Spring 2026,Fall 2025", "avg_enrollment": 111.4,
     "has_page": True},
    {"subject_course": "CS3101", "course_title": "Lab for CS 3100",
     "terms_taught": 3, "last_term_label": "Fall 2026", "recent_terms": "Fall 2026",
     "avg_enrollment": 30.0, "has_page": False},
    {"subject_course": "CS1810", "course_title": "Recitation for CS 1800",
     "terms_taught": 1, "last_term_label": "Fall 2021", "recent_terms": "Fall 2021",
     "avg_enrollment": 30.0, "has_page": False},
    {"subject_course": "CS3500", "course_title": "Object-Oriented Design",
     "terms_taught": 6, "last_term_label": "Spring 2025",
     "recent_terms": "Spring 2025,Fall 2024", "avg_enrollment": None, "has_page": True},
]


def test_professor_history_lists_courses_without_labs_or_recitations():
    query, _, seen = stub(many=lambda s, p: PROF_ROWS)
    got = th.professor_course_history("lucia-nunez", query)
    assert [c["code"] for c in got] == ["CS3100", "CS3500"]
    assert got[0] == {"code": "CS3100", "name": "Program Design and Implementation 2",
                      "termsTaught": 3, "lastTerm": "Fall 2026",
                      "recentTerms": ["Fall 2026", "Spring 2026", "Fall 2025"],
                      "avgClassSize": 111, "hasPage": True}
    assert seen[0][1] == ("lucia-nunez",)


# ── teaching chip ───────────────────────────────────────────────────────

def chip_db(row, linkable=("CS3100",)):
    def one(sql, params):
        if "FROM professor_teaching" in sql:
            return row
        raise AssertionError(sql)

    def many(sql, params):
        if "FROM course_catalog" in sql:
            return [{"code": c} for c in params[0] if c in linkable]
        raise AssertionError(sql)

    return stub(one, many)


TEACHING = {"term_desc": "Fall 2026", "course_codes": "CS3100,CS4530",
            "campuses": "Boston|Oakland, CA", "scraped_at": NOW - timedelta(days=2)}


def test_teaching_chip():
    query, query_one, _ = chip_db(TEACHING)
    assert th.teaching_now("lucia nunez", query, query_one, now=NOW) == {
        "termDesc": "Fall 2026", "courseCodes": ["CS3100", "CS4530"],
        "campuses": ["Boston", "Oakland, CA"], "linkableCodes": ["CS3100"],
    }


def test_teaching_chip_absent_without_a_row():
    query, query_one, _ = chip_db(None)
    assert th.teaching_now("lucia nunez", query, query_one, now=NOW) is None


def test_teaching_chip_hidden_when_stale():
    query, query_one, _ = chip_db({**TEACHING, "scraped_at": NOW - timedelta(days=22)})
    assert th.teaching_now("lucia nunez", query, query_one, now=NOW) is None


def test_teaching_chip_naive_timestamp_read_as_utc():
    naive = (NOW - timedelta(days=1)).replace(tzinfo=None)
    query, query_one, _ = chip_db({**TEACHING, "scraped_at": naive})
    assert th.teaching_now("lucia nunez", query, query_one, now=NOW) is not None


def test_teaching_chip_hidden_for_roster_artifacts():
    codes = ",".join(f"PHYS{1000 + i}" for i in range(th.TEACHING_MAX_COURSES + 1))
    query, query_one, _ = chip_db({**TEACHING, "course_codes": codes})
    assert th.teaching_now("x", query, query_one, now=NOW) is None


# ── names ───────────────────────────────────────────────────────────────

def test_display_name_flips_banner_order():
    assert th.display_name("Nunez, Lucia") == "Lucia Nunez"
    assert th.display_name("Madonna") == "Madonna"
    assert th.display_name(None) is None
