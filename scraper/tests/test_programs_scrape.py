"""Program list: how the catalog tells majors from minors, and the gate on a thin catalog.

The catalog has no single list of programs. Every college lays its program
pages out differently (tabs, combined-major pages, interdisciplinary pages),
but every program has its own page titled "<Name>, <Degree> (<Campus>)" and
every minor "<Name>, Minor". Fixtures are real titles captured 2026-11-20.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
import programs_scrape  # noqa: E402
from programs_scrape import build, parse_program_page  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "catalog", "programs")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


PAGES = {
    "/sitemap.xml": "sitemap.xml",
    "/undergraduate/": "index.html",
    "/undergraduate/computer-information-science/computer-science/bscs/": "major_boston.html",
    "/undergraduate/computer-information-science/computer-science/bscs-oak/": "major_oakland.html",
    "/undergraduate/computer-information-science/computer-science/bacs/": "major_ba.html",
    "/undergraduate/computer-information-science/computer-science/minor/": "minor.html",
    "/undergraduate/computer-information-science/computer-science/": "department_page.html",
    "/undergraduate/business/business-administration-combined-majors/"
    "business-administration-psychology-bs/": "major_combined.html",
}


def fake_fetch(path):
    return fixture(PAGES[path])


def test_parse_finds_majors_and_minors_on_a_program_page():
    assert parse_program_page(fixture("major_boston.html")) == ("major", "Computer Science, BSCS")
    assert parse_program_page(fixture("major_ba.html")) == ("major", "Computer Science, BACS")
    assert parse_program_page(fixture("major_combined.html")) == (
        "major", "Business Administration and Psychology, BS")
    assert parse_program_page(fixture("minor.html")) == ("minor", "Computer Science, Minor")


def test_parse_skips_pages_that_are_not_programs():
    assert parse_program_page(fixture("department_page.html")) is None


def test_build_groups_by_college_and_sorts():
    result = build(fake_fetch, min_majors=1, min_minors=1)
    assert result["source"] == "https://catalog.northeastern.edu/undergraduate/"
    assert set(result) == {"source", "copied", "majors", "minors"}
    # The Boston and Oakland BSCS pages are one major.
    assert result["majors"] == [
        {"name": "Business Administration and Psychology, BS",
         "college": "D'Amore-McKim School of Business"},
        {"name": "Computer Science, BACS", "college": "Khoury College of Computer Sciences"},
        {"name": "Computer Science, BSCS", "college": "Khoury College of Computer Sciences"},
    ]
    assert result["minors"] == [
        {"name": "Computer Science, Minor", "college": "Khoury College of Computer Sciences"}]


def test_build_refuses_a_thin_catalog():
    def thin(path):
        return fixture("department_page.html") if path not in ("/sitemap.xml", "/undergraduate/") \
            else fake_fetch(path)
    with pytest.raises(programs_scrape.ThinCatalog):
        build(thin)
