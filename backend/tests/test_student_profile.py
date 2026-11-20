"""validate_profile: the grad year, majors and minors a student may save."""

import pytest

import programs
from student_profile import validate_profile

M1, M2 = sorted(programs.MAJORS)[:2]
N1 = sorted(programs.MINORS)[0]
assert M1 not in programs.MINORS


def test_undergrad_profile_is_cleaned():
    clean, err = validate_profile({"gradYear": 2028, "majors": [f" {M1} ", M1, "other"], "minors": [N1]}, 2026)
    assert err is None and clean == {"grad_year": 2028, "majors": [M1, "other"], "minors": [N1]}


def test_grad_student_has_no_programs():
    assert validate_profile({"gradYear": None, "majors": [], "minors": []}, 2026)[0] == \
        {"grad_year": None, "majors": [], "minors": []}
    assert validate_profile({"gradYear": None, "majors": [M1], "minors": []}, 2026)[1]


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
