"""validate_profile: the grad year, majors and minors a student may save."""

import pytest

import programs
from student_profile import rater_profile, record_view, validate_profile, validate_view

M1, M2 = sorted(programs.MAJORS)[:2]
N1 = sorted(programs.MINORS)[0]
assert M1 not in programs.MINORS


def test_undergrad_profile_is_cleaned():
    clean, err = validate_profile({"gradYear": 2028, "majors": [f" {M1} ", M1, "other"], "minors": [N1]}, 2026)
    assert err is None and clean == {"level": "undergrad", "grad_year": 2028, "majors": [M1, "other"], "minors": [N1]}


def test_grad_student_has_no_programs():
    assert validate_profile({"gradYear": None, "majors": [], "minors": []}, 2026)[0] == \
        {"level": "grad", "grad_year": None, "majors": [], "minors": []}
    assert validate_profile({"gradYear": None, "majors": [M1], "minors": []}, 2026)[1]


@pytest.mark.parametrize("profile,expected", [
    (None, (None, None)),
    ({"level": "undergrad", "grad_year": 2028, "tracking_opt_out": False}, ("undergrad", 2028)),
    ({"level": "grad", "grad_year": None, "tracking_opt_out": False}, ("grad", None)),
    ({"level": "undergrad", "grad_year": 2028, "tracking_opt_out": True}, (None, None)),
    ({"level": None, "grad_year": None, "tracking_opt_out": True}, (None, None)),   # the opt-out stub
])
def test_rater_profile(profile, expected):
    assert rater_profile("vh1", lambda sql, params=(): profile) == expected


def test_rater_profile_without_a_sub_queries_nothing():
    def boom(sql, params=()):
        raise AssertionError("no query")
    assert rater_profile(None, boom) == (None, None)


@pytest.mark.parametrize("year", [2024, 2032, True, "2028", 2028.5])
def test_bad_year_is_rejected(year):
    assert validate_profile({"gradYear": year, "majors": [M1], "minors": []}, 2026)[1]


def test_year_range_allows_last_year_for_the_new_year_boundary():
    assert validate_profile({"gradYear": 2025, "majors": [M1], "minors": []}, 2026)[1] is None
    assert validate_profile({"gradYear": 2031, "majors": [M1], "minors": []}, 2026)[1] is None


@pytest.mark.parametrize("body", [
    {"gradYear": 2028, "majors": [], "minors": []},                 # undergrad needs a major
    {"gradYear": 2028, "majors": ["Basket Weaving, BS"], "minors": []},
    {"gradYear": 2028, "majors": [M1], "minors": [M1]},              # a major isn't a minor
    {"gradYear": 2028, "majors": [M1, M2, "other", "x", "y"], "minors": []},
    {"gradYear": 2028, "majors": M1, "minors": []},                  # not a list
    {"gradYear": 2028, "majors": [3], "minors": []},
    {"majors": [M1], "minors": []},                                  # gradYear missing
])
def test_bad_programs_are_rejected(body):
    assert validate_profile(body, 2026)[1]


BASE = {"itemType": "professor", "itemKey": "alice-smith", "visibleSeconds": 30, "reachedSection": True, "courseFilter": None}


def test_view_is_cleaned():
    assert validate_view(BASE) == ({"item_type": "professor", "item_key": "alice-smith", "visible_seconds": 30,
                                    "reached_section": True, "course_filter": None}, None)


def test_visible_seconds_clamps_to_30_minutes():
    assert validate_view({**BASE, "visibleSeconds": 10**9})[0]["visible_seconds"] == 1800


@pytest.mark.parametrize("field,value", [
    ("itemType", "department"), ("itemKey", ""), ("itemKey", "x" * 201), ("visibleSeconds", True),
    ("visibleSeconds", "30"), ("visibleSeconds", -5), ("visibleSeconds", 3.5), ("reachedSection", "yes"),
])
def test_bad_view_is_rejected(field, value):
    assert validate_view({**BASE, field: value})[1]


@pytest.mark.parametrize("raw,clean", [(" cs 3500 ", "CS3500"), (123, None), ("<script>", "<SCRIPT>"), ("  ", None)])
def test_course_filter_is_normalized_not_rejected(raw, clean):
    assert validate_view({**BASE, "courseFilter": raw})[0]["course_filter"] == clean


CLEAN = {"item_type": "professor", "item_key": "alice-smith", "visible_seconds": 30,
         "reached_section": True, "course_filter": "CS2500"}


def fakes(profile, catalog):
    log = {"queries": [], "writes": []}

    def query_one(sql, params=()):
        log["queries"].append((sql, params))
        if "FROM student_profiles" in sql:
            return profile
        return {"?column?": 1} if params in catalog else None

    def write(sql, params=None):
        log["writes"].append((sql, params))

    return query_one, write, log


def test_view_without_a_profile_is_ignored_with_no_further_query():
    q, w, log = fakes(None, set())
    assert record_view("vh1", CLEAN, q, w) == "ignored"
    assert len(log["queries"]) == 1 and log["writes"] == []


def test_view_with_an_opted_out_profile_is_ignored():
    q, w, log = fakes({"tracking_opt_out": True}, {("alice-smith",)})
    assert record_view("vh1", CLEAN, q, w) == "ignored"
    assert len(log["queries"]) == 1 and log["writes"] == []


def test_view_of_an_unknown_item_is_not_found():
    q, w, log = fakes({"tracking_opt_out": False}, set())
    assert record_view("vh1", CLEAN, q, w) == "not_found"
    assert log["writes"] == []


def test_professor_view_stores_a_real_course_filter():
    q, w, log = fakes({"tracking_opt_out": False}, {("alice-smith",), ("CS2500",)})
    assert record_view("vh1", CLEAN, q, w) == "ok"
    params = log["writes"][0][1]
    assert params == ("vh1", "professor", "alice-smith", 30, True, "CS2500", "vh1")


def test_professor_view_drops_a_course_filter_not_in_the_catalog():
    q, w, log = fakes({"tracking_opt_out": False}, {("alice-smith",)})
    assert record_view("vh1", {**CLEAN, "course_filter": "CS9999"}, q, w) == "ok"
    assert log["writes"][0][1][-2] is None


def test_course_view_always_stores_a_null_course_filter():
    q, w, log = fakes({"tracking_opt_out": False}, {("CS2500",)})
    view = {**CLEAN, "item_type": "course", "item_key": "CS2500"}
    assert record_view("vh1", view, q, w) == "ok"
    assert log["writes"][0][1] == ("vh1", "course", "CS2500", 30, True, None, "vh1")


def test_view_insert_rechecks_the_profile_under_a_share_lock_and_stores_no_sub():
    q, w, log = fakes({"tracking_opt_out": False}, {("alice-smith",)})
    record_view("vh1", {**CLEAN, "course_filter": None}, q, w)
    sql, params = log["writes"][0]
    assert "NOT tracking_opt_out FOR SHARE" in sql and "viewer_hash" in sql and "user_sub" not in sql
    assert params[0] == "vh1" and params.count("vh1") == 2 and params[-1] == "vh1"
