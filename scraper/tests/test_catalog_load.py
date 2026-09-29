"""Catalog loader behaviour against a real sqlite database.

The logic under test is SQL, so a fake cursor would assert nothing — same
reasoning as test_banner_load.py.

The load is a wholesale replacement of one edition by the next, which makes
deletion a first-class case rather than an afterthought: a course really does
leave the catalog mid-edition (ENGL 3467 vanished from the live site in October
2025 while TRACE still rates it), and an attribute really is removed from a
course that keeps its other ones.
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
from load_catalog_to_crdb import (DDL, SanityGateFailed,  # noqa: E402
                                  build_rows, check_gates, normalize_text,
                                  previous_count, prune_stale, replace_nupath,
                                  upsert_courses)


@pytest.fixture
def cur():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    for stmt in DDL.split(";"):
        if stmt.strip():
            c.execute(stmt.replace("TIMESTAMPTZ", "TIMESTAMP")
                         .replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP"))
    return c


def course(code="CS3000", name="Algorithms and Data", nupath=(), slug="cs",
           description="Introduces algorithms.", credits="4 Hours"):
    return {"code": code, "subject": code[:2], "number": code[2:], "name": name,
            "credit_hours": credits, "credit_min": 4.0, "credit_max": 4.0,
            "description": description, "prerequisites": None,
            "corequisites": None, "nupath": list(nupath), "subject_slug": slug}


def scrape(*courses, year="2025-2026", slug="cs", department="Computer Science"):
    return {"scraped_at": "2026-08-13", "course_count": len(courses),
            "subjects": [{"slug": slug, "subject": "CS", "department": department}],
            "courses": list(courses)}


def load(cur, scraped, year="2025-2026"):
    rows, nupath = build_rows(scraped, catalog_year=year)
    codes = {r["code"] for r in rows}
    upsert_courses(cur, rows)
    replace_nupath(cur, nupath, codes)
    prune_stale(cur, codes)
    return rows


# --- building rows ---

def test_department_comes_from_the_subject_index():
    rows, _ = build_rows(scrape(course()), catalog_year="2025-2026")
    assert rows[0]["department"] == "Computer Science"


def test_catalog_year_is_stamped_on_every_row():
    rows, _ = build_rows(scrape(course(), course("CS2500")), catalog_year="2026-2027")
    assert {r["catalog_year"] for r in rows} == {"2026-2027"}


def test_nupath_becomes_one_row_per_attribute():
    _, nupath = build_rows(
        scrape(course(nupath=["Formal/Quant Reasoning", "Natural/Designed World"])),
        catalog_year="2025-2026")
    assert sorted(nupath) == [("CS3000", "Formal/Quant Reasoning"),
                             ("CS3000", "Natural/Designed World")]


# --- search_text: the catalog's punctuation is not the user's ---

def test_curly_apostrophe_is_normalized_so_a_typed_quote_matches():
    """The catalog writes 'Journalist’s'; a student types "Journalist's"."""
    rows, _ = build_rows(scrape(course(code="JRNL1102", name="Journalist’s Toolbox")),
                         catalog_year="2025-2026")
    assert "journalist's toolbox" in rows[0]["search_text"]


def test_en_dash_is_normalized_to_a_hyphen():
    rows, _ = build_rows(scrape(course(code="BINF6900", name="Pre–Co-op Experience")),
                         catalog_year="2025-2026")
    assert "pre-co-op" in rows[0]["search_text"]


def test_display_name_keeps_the_catalogs_own_glyphs():
    """Normalisation is for matching only — the page still shows the real title."""
    rows, _ = build_rows(scrape(course(code="JRNL1102", name="Journalist’s Toolbox")),
                         catalog_year="2025-2026")
    assert rows[0]["name"] == "Journalist’s Toolbox"


def test_search_text_includes_the_description_and_nupath():
    rows, _ = build_rows(
        scrape(course(description="Covers thermodynamics.", nupath=["Writing Intensive"])),
        catalog_year="2025-2026")
    text = rows[0]["search_text"]
    assert "thermodynamics" in text and "writing intensive" in text and "cs3000" in text


def test_normalize_text_is_idempotent():
    assert normalize_text(normalize_text("Journalist’s Pre–Co-op")) == \
        normalize_text("Journalist’s Pre–Co-op")


# --- is_placeholder ---
#
# Ground truth for "this is a real class" is a TRACE rating: something was
# taught and students evaluated it. Measured across the 7,966-course scrape,
# these titles have *never* carried a rating on any code — while `Topics` (11
# rated), `Thesis` (4), `Seminar` (2) and `Capstone` (1) have, which is why a
# generic-sounding title is not on its own enough.

@pytest.mark.parametrize("name", [
    "Elective", "Research", "Directed Study", "Independent Study",
    "Project", "Internship",
])
def test_titles_trace_has_never_rated_are_placeholders(name):
    rows, _ = build_rows(scrape(course(code="CS4100", name=name)), catalog_year="2025-2026")
    assert rows[0]["is_placeholder"] is True


@pytest.mark.parametrize("name", [
    "Topics", "Special Topics", "Seminar", "Capstone", "Thesis", "Practicum",
])
def test_generic_titles_that_do_get_rated_are_not_placeholders(name):
    """TRACE rates real classes under every one of these titles."""
    rows, _ = build_rows(scrape(course(code="CS4100", name=name)), catalog_year="2025-2026")
    assert rows[0]["is_placeholder"] is False


@pytest.mark.parametrize("name", [
    "Research Methods and Scientific Writing",
    "Research Capstone",
    "Project Management",
    "Independent Study in Physics",
])
def test_a_real_course_that_merely_starts_with_a_generic_word_is_not_flagged(name):
    """A prefix rule flags 62 rated courses; matching the whole title flags none."""
    rows, _ = build_rows(scrape(course(code="CS4100", name=name)), catalog_year="2025-2026")
    assert rows[0]["is_placeholder"] is False


@pytest.mark.parametrize("name", [
    "Dissertation", "Dissertation Term 1", "Dissertation Continuation",
    "Thesis Continuation - Half-Time", "Candidacy Continuation",
])
def test_dissertation_family_titles_are_placeholders(name):
    rows, _ = build_rows(scrape(course(code="CS9990", name=name)), catalog_year="2025-2026")
    assert rows[0]["is_placeholder"] is True


def test_the_x99x_code_block_is_a_placeholder_whatever_it_is_called():
    """1,103 codes, 11 of them rated — the flag is advisory, see the docstring."""
    rows, _ = build_rows(scrape(course(code="ECON4998", name="Senior Economics Thesis")),
                         catalog_year="2025-2026")
    assert rows[0]["is_placeholder"] is True


def test_an_ordinary_course_is_not_a_placeholder():
    rows, _ = build_rows(scrape(course(code="CS3000", name="Algorithms and Data")),
                         catalog_year="2025-2026")
    assert rows[0]["is_placeholder"] is False


def test_the_flag_reaches_the_database_and_is_queryable(cur):
    load(cur, scrape(course("CS3000", name="Algorithms and Data"),
                     course("CS4990", name="Elective")))
    real = cur.execute(
        "SELECT code FROM catalog_courses WHERE NOT is_placeholder").fetchall()
    assert [r[0] for r in real] == ["CS3000"]


def test_the_flag_updates_when_a_course_stops_being_one(cur):
    load(cur, scrape(course("CS4100", name="Elective")))
    load(cur, scrape(course("CS4100", name="Algorithms and Data")))
    assert cur.execute("SELECT is_placeholder FROM catalog_courses").fetchone()[0] == 0


# --- upsert ---

def test_upsert_inserts_rows(cur):
    load(cur, scrape(course("CS3000"), course("CS2500")))
    assert cur.execute("SELECT count(*) FROM catalog_courses").fetchone()[0] == 2


def test_upsert_is_idempotent(cur):
    load(cur, scrape(course("CS3000")))
    load(cur, scrape(course("CS3000")))
    assert cur.execute("SELECT count(*) FROM catalog_courses").fetchone()[0] == 1


def test_a_renamed_course_takes_the_new_title(cur):
    load(cur, scrape(course("CS5350", name="Applied Geometric Rep")))
    load(cur, scrape(course("CS5350", name="Computational Geometry")))
    assert cur.execute("SELECT name FROM catalog_courses").fetchone()[0] == "Computational Geometry"


# --- nupath replacement ---

def test_nupath_rows_are_written(cur):
    load(cur, scrape(course("CS3000", nupath=["Formal/Quant Reasoning"])))
    assert cur.execute("SELECT attribute FROM catalog_nupath").fetchone()[0] == "Formal/Quant Reasoning"


def test_an_attribute_removed_from_a_course_is_deleted(cur):
    """Writing Intensive is section-specific and does get dropped between editions."""
    load(cur, scrape(course("CS3000", nupath=["Formal/Quant Reasoning", "Writing Intensive"])))
    load(cur, scrape(course("CS3000", nupath=["Formal/Quant Reasoning"])))
    got = [r[0] for r in cur.execute("SELECT attribute FROM catalog_nupath").fetchall()]
    assert got == ["Formal/Quant Reasoning"]


def test_a_course_losing_every_attribute_keeps_no_nupath_rows(cur):
    load(cur, scrape(course("CS3000", nupath=["Writing Intensive"])))
    load(cur, scrape(course("CS3000", nupath=[])))
    assert cur.execute("SELECT count(*) FROM catalog_nupath").fetchone()[0] == 0


# --- pruning: a course can leave the catalog ---

def test_a_course_removed_from_the_catalog_is_pruned(cur):
    """ENGL 3467 disappeared from the live page in October 2025."""
    load(cur, scrape(course("ENGL3467"), course("ENGL1111")))
    load(cur, scrape(course("ENGL1111")))
    codes = [r[0] for r in cur.execute("SELECT code FROM catalog_courses").fetchall()]
    assert codes == ["ENGL1111"]


def test_pruning_a_course_takes_its_nupath_rows_with_it(cur):
    load(cur, scrape(course("ENGL3467", nupath=["Creative Express/Innov"]),
                     course("ENGL1111")))
    load(cur, scrape(course("ENGL1111")))
    assert cur.execute("SELECT count(*) FROM catalog_nupath").fetchone()[0] == 0


def test_pruning_leaves_courses_that_are_still_listed(cur):
    load(cur, scrape(course("CS3000"), course("CS2500")))
    assert cur.execute("SELECT count(*) FROM catalog_courses").fetchone()[0] == 2


def test_prune_handles_more_codes_than_one_statement_should_bind(cur):
    """A single NOT IN with 8,000 parameters is how this breaks in production."""
    many = [course(f"CS{2000 + i}") for i in range(3000)]
    load(cur, scrape(*many))
    load(cur, scrape(*many[:1500]))
    assert cur.execute("SELECT count(*) FROM catalog_courses").fetchone()[0] == 1500


# --- gates ---

def test_a_large_drop_against_the_loaded_table_aborts():
    with pytest.raises(SanityGateFailed, match="previous"):
        check_gates([{"code": f"C{i}"} for i in range(4000)], previous=7966)


def test_a_small_drop_is_within_tolerance():
    check_gates([{"code": f"C{i}"} for i in range(7500)], previous=7966)


def test_first_ever_load_has_no_baseline_to_compare(cur):
    assert previous_count(cur) == 0
    check_gates([{"code": "CS3000"}], previous=0)


def test_an_empty_scrape_never_loads():
    with pytest.raises(SanityGateFailed):
        check_gates([], previous=0)


def test_previous_count_reads_the_loaded_table(cur):
    load(cur, scrape(course("CS3000"), course("CS2500")))
    assert previous_count(cur) == 2
