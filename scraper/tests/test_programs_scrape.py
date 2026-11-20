"""Program list: how the catalog tells majors from minors, and the gate on a thin catalog.

The catalog has no single list of programs. Every college lays its program
pages out differently (tabs, combined-major pages, interdisciplinary pages),
but every program has its own page titled "<Name>, <Degree> (<Campus>)" and
every minor "<Name>, Minor". Fixtures are real titles captured 2026-11-20.
"""
import os
import sys

import pytest
import requests

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
    result = build(fake_fetch, min_majors=1, min_minors=1, archive_years=())
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


def title_page(title):
    return f"<html><head><title>{title} &lt; Northeastern University Academic Catalog</title></head></html>"


@pytest.mark.parametrize("title, expected", [
    ("History, Culture, and Law, BA (Boston)", ("major", "History, Culture, and Law, BA")),
    ("Pharmacy, PharmD (Boston)", ("major", "Pharmacy, PharmD")),
    ("Computer Science, BA (Boston", ("major", "Computer Science, BA")),
    ("Marine Biology, BS with Three Seas", ("major", "Marine Biology, BS")),
    ("Chemical Engineering, BSChE (Boston)", ("major", "Chemical Engineering, BSChE")),
    ("Biology, Minor", ("minor", "Biology, Minor")),
    ("X, Biology (Boston)", None),
    ("Pre-Law, Boston", None),
])
def test_parse_titles(title, expected):
    assert parse_program_page(title_page(title)) == expected


def test_archive_editions_are_unioned_and_deduped_keeping_the_current_college():
    def sitemap(*slugs):
        locs = "".join(f"<loc>https://catalog.northeastern.edu/undergraduate/{s}/</loc>" for s in slugs)
        return f"<urlset>{locs}</urlset>"

    def index(prefix, label_a, label_b):
        return (f'<a href="{prefix}/undergraduate/college-a/">{label_a}</a>'
                f'<a href="{prefix}/undergraduate/college-b/">{label_b}</a>')

    pages = {
        "/undergraduate/": index("", "Current A", "Current B"),
        "/sitemap.xml": sitemap("college-a/shared", "college-a/new"),
        "/undergraduate/college-a/shared/": title_page("Shared, BS (Boston)"),
        "/undergraduate/college-a/new/": title_page("Newer, BS (Boston)"),
        "/archive/2025-2026/undergraduate/": index("/archive/2025-2026", "Old A", "Old B"),
        "/archive/2025-2026/sitemap.xml": sitemap("college-b/shared", "college-b/gone"),
        "/archive/2025-2026/undergraduate/college-b/shared/": title_page("Shared, BS (Boston)"),
        "/archive/2025-2026/undergraduate/college-b/gone/": title_page("Data Science, BS (Boston)"),
    }
    result = build(pages.__getitem__, min_majors=1, min_minors=0, archive_years=("2025-2026",))
    assert result["source"] == "https://catalog.northeastern.edu/undergraduate/"
    assert result["majors"] == [
        {"name": "Newer, BS", "college": "Current A"},
        {"name": "Shared, BS", "college": "Current A"},
        {"name": "Data Science, BS", "college": "Old B"},
    ]


def test_an_older_title_for_the_same_page_is_not_a_second_program():
    # The 2022-2024 catalogs titled /business/business-administration-bsba/
    # "Bachelor of Science in Business Administration, BSBA".
    pages = {
        "/undergraduate/": '<a href="/undergraduate/business/">Business</a>',
        "/sitemap.xml": "<urlset><loc>https://catalog.northeastern.edu/undergraduate/business/ba-bsba/</loc></urlset>",
        "/undergraduate/business/ba-bsba/": title_page("Business Administration, BSBA (Boston)"),
        "/archive/2023-2024/undergraduate/": '<a href="/archive/2023-2024/undergraduate/business/">Business</a>',
        "/archive/2023-2024/sitemap.xml":
            "<urlset><loc>http://catalog.northeastern.edu/undergraduate/business/ba-bsba/</loc></urlset>",
        "/archive/2023-2024/undergraduate/business/ba-bsba/":
            title_page("Bachelor of Science in Business Administration, BSBA"),
    }
    result = build(pages.__getitem__, min_majors=1, min_minors=0, archive_years=("2023-2024",))
    assert result["majors"] == [{"name": "Business Administration, BSBA", "college": "Business"}]


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status}", response=response)


def archive_pages(archive_index):
    return {
        "/undergraduate/": '<a href="/undergraduate/business/">Business</a>',
        "/sitemap.xml": "<urlset><loc>https://catalog.northeastern.edu/undergraduate/business/a/</loc>"
                        "<loc>https://catalog.northeastern.edu/undergraduate/business/b/</loc></urlset>",
        "/undergraduate/business/a/": title_page("A, BS (Boston)"),
        "/undergraduate/business/b/": title_page("B, Minor"),
        "/archive/2025-2026/undergraduate/": archive_index,
        "/archive/2025-2026/sitemap.xml":
            "<urlset><loc>http://catalog.northeastern.edu/undergraduate/business/a/</loc>"
            "<loc>http://catalog.northeastern.edu/undergraduate/business/b/</loc></urlset>",
        "/archive/2025-2026/undergraduate/business/a/": title_page("A, BS (Boston)"),
        "/archive/2025-2026/undergraduate/business/b/": title_page("B, Minor"),
    }


def test_build_refuses_an_archive_edition_that_yields_nothing():
    pages = archive_pages("<html>redesigned</html>")
    with pytest.raises(programs_scrape.ThinCatalog, match="2025-2026"):
        build(pages.__getitem__, min_majors=1, min_minors=1, archive_years=("2025-2026",))


def test_build_accepts_a_healthy_archive_edition():
    pages = archive_pages('<a href="/archive/2025-2026/undergraduate/business/">Business</a>')
    result = build(pages.__getitem__, min_majors=1, min_minors=1, archive_years=("2025-2026",))
    assert [m["name"] for m in result["majors"]] == ["A, BS"]


def program_pages_with(fetch_error):
    pages = {
        "/undergraduate/": '<a href="/undergraduate/business/">Business</a>',
        "/sitemap.xml": "<urlset><loc>https://catalog.northeastern.edu/undergraduate/business/a/</loc>"
                        "<loc>https://catalog.northeastern.edu/undergraduate/business/stale/</loc></urlset>",
        "/undergraduate/business/a/": title_page("A, BS (Boston)"),
    }

    def fetch(path):
        if path in pages:
            return pages[path]
        raise fetch_error
    return fetch


@pytest.mark.parametrize("status", [404, 410])
def test_a_missing_program_page_is_skipped_and_the_rest_kept(status, capsys):
    result = build(program_pages_with(http_error(status)), min_majors=1, min_minors=0, archive_years=())
    assert [m["name"] for m in result["majors"]] == ["A, BS"]
    assert "skipped 1 program pages" in capsys.readouterr().err


@pytest.mark.parametrize("path", ["/undergraduate/", "/sitemap.xml"])
def test_a_missing_index_or_sitemap_still_raises(path):
    pages = program_pages_with(http_error(404))

    def fetch(p):
        if p == path:
            raise http_error(404)
        return pages(p)
    with pytest.raises(requests.HTTPError):
        build(fetch, min_majors=1, min_minors=0, archive_years=())


def test_a_server_error_on_a_program_page_still_raises():
    with pytest.raises(requests.HTTPError):
        build(program_pages_with(http_error(500)), min_majors=1, min_minors=0, archive_years=())
