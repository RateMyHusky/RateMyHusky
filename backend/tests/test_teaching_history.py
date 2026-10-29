"""Banner-derived teaching history for course and professor pages.

The DB is stubbed by keying on the SQL text, as in test_course_api.py.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

import teaching_history as th

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)

OFFERING = {
    "subject_course": "CS3100", "course_title": "Program Design and Implementation 2",
    "last_term_label": "Fall 2026", "pattern": "Fall and Spring",
    "median_section_size": 98.0, "credit_hours": "4",
    "offered_now": "Fall 2026",
    "first_term_code": "202610", "first_term_label": "Fall 2025",
    "offering_years": json.dumps({"window": [2026], "Fall": [2026], "Spring": [2026],
                                  "Summer 1": [2026], "Summer 2": [], "Summer": []}),
}

INSTRUCTORS = [
    {"instructor_name": "Nunez, Lucia", "professor_slug": "lucia-nunez", "catalog_name": "Lucia Nunez",
     "terms_taught": 3, "last_term_code": "202710", "last_term_label": "Fall 2026",
     "recent_terms": "Fall 2026,Spring 2026,Fall 2025", "avg_enrollment": 111.06,
     "image_url": "https://img/n.jpg", "focus_x": 40.0, "focus_y": 20.0,
     "total_comments": 41, "would_take_again_pct": 86.66},
    {"instructor_name": "Doe, Jane Q", "professor_slug": None, "catalog_name": None,
     "terms_taught": 1, "last_term_code": "202630", "last_term_label": "Spring 2026",
     "recent_terms": "Spring 2026", "avg_enrollment": None,
     "image_url": None, "focus_x": None, "focus_y": None,
     "total_comments": None, "would_take_again_pct": None},
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
    assert got["lastOffered"] == "Fall 2026"
    assert got["offeredNow"] == ["Fall 2026"]
    assert got["creditHours"] == "4"
    assert got["typicalClassSize"] == 98


def test_course_history_offering_years_use_the_season_keys_and_the_first_year():
    query, query_one, _ = course_db()
    got = th.course_history("CS3100", query, query_one)
    assert got["offeringYears"] == {"window": [2026], "first": 2026,
                                    "fall": [2026], "spring": [2026], "summer1": [2026],
                                    "summer2": [], "summer": []}
    assert got["firstOffered"] == "Fall 2025"


def test_offering_years_are_null_before_the_scraper_stores_them():
    query, query_one, _ = course_db(offerings={"CS3100": {**OFFERING, "offering_years": None}})
    assert th.course_history("CS3100", query, query_one)["offeringYears"] is None


def test_offering_query_selects_the_years_and_first_term():
    query, query_one, seen = course_db()
    th.course_history("CS3100", query, query_one)
    sql = next(s for s, _ in seen if "FROM banner_course_offerings" in s)
    assert "offering_years" in sql and "first_term_code" in sql and "first_term_label" in sql


def test_course_history_instructors_link_matched_and_name_the_rest():
    query, query_one, _ = course_db()
    got = th.course_history("CS3100", query, query_one)["instructors"]
    assert got[0] == {"name": "Lucia Nunez", "slug": "lucia-nunez", "termsTaught": 3,
                      "lastTerm": "Fall 2026",
                      "recentTerms": ["Fall 2026", "Spring 2026", "Fall 2025"],
                      "avgClassSize": 111, "imageUrl": "https://img/n.jpg",
                      "focusX": 40.0, "focusY": 20.0,
                      "totalComments": 41, "wouldTakeAgainPct": 86.7}
    assert got[1]["name"] == "Jane Q Doe"
    assert got[1]["slug"] is None
    assert got[1]["avgClassSize"] is None


def test_unmatched_instructor_has_no_photo_and_the_default_focus():
    query, query_one, _ = course_db()
    jane = th.course_history("CS3100", query, query_one)["instructors"][1]
    assert (jane["imageUrl"], jane["focusX"], jane["focusY"]) == (None, 50.0, 30.0)


def test_instructor_query_selects_term_code_and_photo():
    query, query_one, seen = course_db()
    th.course_history("CS3100", query, query_one)
    sql = next(s for s, _ in seen if "FROM banner_course_instructors" in s)
    assert "bci.last_term_code" in sql
    assert "pc.image_url" in sql and "pc.focus_x" in sql and "pc.focus_y" in sql
    assert "pc.total_comments" in sql and "pc.would_take_again_pct" in sql


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
    assert (got["offeringYears"], got["firstOffered"]) == (None, None)


def test_successors_are_khourys_published_mapping():
    assert th.COURSE_SUCCESSORS == {
        "CS2500": ("CS2000", "Fall 2025"),
        "CS2510": ("CS2100", "Fall 2025"),
        "CS3500": ("CS3100", "Fall 2025"),
    }


def test_summer_2_sorts_ahead_of_summer_1_on_their_shared_code():
    # From 2026 both sessions are term 202650; the SQL order (most terms first) is wrong.
    rows = [{**INSTRUCTORS[0], "last_term_code": "202650", "last_term_label": "Summer 1 2026",
             "terms_taught": 8},
            {**INSTRUCTORS[1], "last_term_code": "202650", "last_term_label": "Summer 2 2026"}]
    query, query_one, _ = course_db(instructors=rows)
    got = th.course_history("CS3100", query, query_one)["instructors"]
    assert [i["lastTerm"] for i in got] == ["Summer 2 2026", "Summer 1 2026"]


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


def test_professor_history_orders_summer_sessions_that_share_a_code():
    rows = [{**PROF_ROWS[3], "last_term_code": "202650", "last_term_label": "Summer 1 2026"},
            {**PROF_ROWS[0], "last_term_code": "202650", "last_term_label": "Summer 2 2026",
             "terms_taught": 2}]
    query, _, _ = stub(many=lambda s, p: rows)
    got = th.professor_course_history("lucia-nunez", query)
    assert [c["code"] for c in got] == ["CS3100", "CS3500"]


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


# ── label codes ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("label, code", [
    ("Fall 2026", 202710),
    ("Winter 2026", 202625),
    ("Spring 2026", 202630),
    ("Summer 1 2026", 202640),
    ("Summer Full 2026", 202650),
    ("Summer 2026", 202650),
    ("Summer 2 2026", 202660),
    ("Fall 2025", 202610),
])
def test_label_code_matches_banners_term_codes(label, code):
    assert th.label_code(label) == code


@pytest.mark.parametrize("label", [None, "", "Fall", "2026", "Autumn 2026", "Fall A 2026", "Fall 26"])
def test_label_code_is_none_for_a_label_it_cannot_read(label):
    assert th.label_code(label) is None


# ── names ───────────────────────────────────────────────────────────────

def test_display_name_flips_banner_order():
    assert th.display_name("Nunez, Lucia") == "Lucia Nunez"
    assert th.display_name("Madonna") == "Madonna"
    assert th.display_name(None) is None
