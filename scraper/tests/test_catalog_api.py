"""Parsing catalog.northeastern.edu course descriptions.

Fixtures are real markup captured 2026-08-13, trimmed to the shapes that
actually occur. Three of them exist because the page lies in ways a naive
parser cannot see:

- subject and number are joined by U+00A0, not a space, so the join key with
  TRACE is wrong in a way that looks right;
- a retired subject slug answers 200 with a "Page Not Found" body, so
  raise_for_status() passes and the subject silently contributes zero courses;
- credit hours are a free-text field holding ranges, comma lists and decimals,
  not an integer.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
from catalog_api import (PageNotFound, parse_courses,  # noqa: E402
                         parse_credit_hours, parse_subject_index)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "catalog")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture
def courses():
    return {c.code: c for c in parse_courses(fixture("subject_courses.html"), "cs")}


# --- the subject index ---

def test_index_yields_slug_subject_and_department():
    subjects = parse_subject_index(fixture("index.html"))
    assert ("cs", "CS", "Computer Science") in [
        (s.slug, s.subject, s.department) for s in subjects]


def test_index_strips_the_zero_width_space_in_department_names():
    """'Art -&#8203; Media Arts' must not reach the database as 'Art -​ Media Arts'."""
    subjects = {s.slug: s for s in parse_subject_index(fixture("index.html"))}
    assert "​" not in subjects["artd"].department
    assert subjects["artd"].department == "Art - Media Arts"


def test_index_ignores_pages_that_are_not_subjects():
    html = fixture("index.html").replace(
        '<li><a href="/course-descriptions/cs/">Computer Science (CS)</a></li>',
        '<li><a href="/archive/">Archived Catalogs</a></li>')
    assert "cs" not in [s.slug for s in parse_subject_index(html)]


# --- course blocks ---

def test_course_code_joins_subject_and_number_with_no_space():
    """TRACE stores 'CS1100'; the catalog renders 'CS 1100'."""
    assert "CS1100" in {c.code for c in parse_courses(fixture("subject_courses.html"), "cs")}


def test_code_carries_no_non_breaking_space():
    for course in parse_courses(fixture("subject_courses.html"), "cs"):
        assert " " not in course.code and " " not in course.code


def test_parses_title_without_the_trailing_period(courses):
    assert courses["CS3000"].name == "Algorithms and Data"


def test_parses_description_as_collapsed_text(courses):
    desc = courses["CS1200"].description
    assert desc.startswith("Seeks to support students in their transition")
    assert desc.endswith("assist with academic and personal goal setting.")
    assert "  " not in desc


def test_prerequisites_are_flattened_to_the_rendered_text(courses):
    """Stored verbatim, links stripped — never parsed into a graph."""
    prereq = courses["CS3000"].prerequisites
    assert prereq.startswith("((CS 2100 with a minimum grade of D-")
    assert "<a href" not in prereq and "bubblelink" not in prereq
    assert "EECE 2160 with a minimum grade of D- ))" in prereq


def test_corequisites_are_captured(courses):
    assert courses["CS1100"].corequisites == "CS 1101"


def test_single_nupath_attribute_drops_the_prefix(courses):
    assert courses["CS1100"].nupath == ["Analyzing/Using Data"]


def test_multiple_nupath_attributes_split_on_the_comma(courses):
    assert courses["CS2000"].nupath == ["Formal/Quant Reasoning", "Natural/Designed World"]


def test_course_with_no_extras_parses_with_empty_fields(courses):
    plain = courses["CS1990"]
    assert plain.nupath == []
    assert plain.prerequisites is None
    assert plain.corequisites is None
    assert plain.description.startswith("Offers elective credit")


def test_every_course_records_the_subject_slug_it_came_from(courses):
    assert {c.subject_slug for c in courses.values()} == {"cs"}


# --- credit hours: free text, not an integer ---

@pytest.mark.parametrize("text,expected", [
    ("4 Hours", (4.0, 4.0)),
    ("1 Hour", (1.0, 1.0)),
    ("0 Hours", (0.0, 0.0)),
    ("1-4 Hours", (1.0, 4.0)),
    ("1,2 Hours", (1.0, 2.0)),
    ("2.25 Hours", (2.25, 2.25)),
    ("3,4 Hours", (3.0, 4.0)),
])
def test_credit_hour_range_is_parsed_from_free_text(text, expected):
    assert parse_credit_hours(text) == expected


def test_unparseable_credit_hours_return_no_range_rather_than_guessing():
    assert parse_credit_hours("Hours TBD") == (None, None)


def test_credit_hours_keep_the_raw_text_too(courses):
    assert courses["CS1990"].credit_hours == "1-4 Hours"
    assert (courses["CS1990"].credit_min, courses["CS1990"].credit_max) == (1.0, 4.0)


# --- the soft 404 ---

def test_soft_404_raises_instead_of_reporting_an_empty_subject():
    """HTTP 200 with a 'Page Not Found' body — the failure raise_for_status misses."""
    with pytest.raises(PageNotFound):
        parse_courses(fixture("subject_not_found.html"), "danc")
