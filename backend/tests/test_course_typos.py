"""Candidate course codes for a typo: one-edit neighbors and subject variants,
and the Banner lookups that keep the real ones."""

import pytest

import course_typos
import rating_checks


@pytest.mark.parametrize("typed, real", [
    ("MGMT4450", "MGMT4550"), ("CS2500", "CS2050"), ("CS2500", "CSE2500"), ("CSE2500", "CS2500"),
    ("BIO2299", "BIOL2299"), ("ACC1201", "ACCT1201"), ("FIN3303", "FINA3303"),
    ("PSY1101", "PSYC1101"), ("CIV2320", "CIVE2320"), ("ECN1115", "ECON1115"), ("CALC1241", "MATH1241"),
])
def test_neighbors_reach_the_real_code(typed, real):
    assert real in course_typos.neighbors(typed)


def test_envr1110_reaches_two_real_codes():
    n = course_typos.neighbors("ENVR1110")
    assert {"ENVR1101", "ENVR1120"} <= n


def test_neighbors_are_valid_codes_and_exclude_the_input():
    n = course_typos.neighbors("CS2500")
    assert "CS2500" not in n and all(rating_checks.COURSE_CODE_RE.fullmatch(c) for c in n)


def test_taught_candidates_queries_once_with_all_neighbors():
    calls = []

    def query(sql, params=()):
        calls.append((sql, params))
        return [{"professor_slug": "a", "subject_course": "CS2510"},
                {"professor_slug": "a", "subject_course": "CS2500"},
                {"professor_slug": "b", "subject_course": "CS2500"}]

    got = course_typos.taught_candidates("CS2501", ["a", "b", "c"], query)
    assert got == {"a": ["CS2500", "CS2510"], "b": ["CS2500"], "c": []}
    assert len(calls) == 1
    sql, params = calls[0]
    assert "subject_course = ANY(%s)" in sql and "professor_slug = ANY(%s)" in sql
    assert sorted(params[0]) == sorted(course_typos.neighbors("CS2501"))
    assert params[1] == ["a", "b", "c"]


def test_banner_candidates_prefer_the_professors_courses():
    calls = []

    def query(sql, params=()):
        calls.append(sql)
        if "banner_course_instructors" in sql:
            return [{"code": "CS2500", "name": "Fundamentals"}]
        return [{"code": "CS2050", "name": "Other"}]

    got = course_typos.banner_candidates("CS2501", query, slug="alice-smith")
    assert got == [{"code": "CS2500", "name": "Fundamentals"}]
    assert len(calls) == 1


def test_banner_candidates_fall_back_to_all_banner():
    def query(sql, params=()):
        if "banner_course_instructors" in sql:
            return []
        return [{"code": "CS2500", "name": "B"}, {"code": "CS2050", "name": "A"}]

    assert course_typos.banner_candidates("CS2501", query, slug="x") == [
        {"code": "CS2050", "name": "A"}, {"code": "CS2500", "name": "B"}]
    assert course_typos.banner_candidates("CS2501", query) == [
        {"code": "CS2050", "name": "A"}, {"code": "CS2500", "name": "B"}]


def test_banner_candidates_cap_at_five_sorted():
    rows = [{"code": f"CS250{i}", "name": None} for i in range(9, 0, -1)]
    got = course_typos.banner_candidates("CS2500", lambda sql, params=(): rows)
    assert [r["code"] for r in got] == [f"CS250{i}" for i in range(1, 6)]
