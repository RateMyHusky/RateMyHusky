"""Banner response parsing and term selection — no network, no DB.

Every fixture in fixtures/banner/ is a trimmed real response captured
2026-08-04. The field names are Banner's; do not tidy them.
"""
import json
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
from banner_api import (  # noqa: E402
    clean_term_desc,
    normalize_instructor_key,
    parse_faculty,
    parse_section,
    parse_term,
    section_end_dates,
    select_season,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "banner")


def fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


# ── normalize_instructor_key ──────────────────────────────────────────────
# Banner is "Last, First"; the catalog's name_key is normalize_name("First Last").
# These two have to meet in the middle or nothing matches.

def test_key_flips_last_comma_first():
    assert normalize_instructor_key("Witte, Annie") == "annie witte"


def test_key_strips_accents_and_case():
    assert normalize_instructor_key("Ramírez, José") == "jose ramirez"


def test_key_keeps_middle_tokens():
    assert normalize_instructor_key("Smith, John A") == "john a smith"


def test_key_handles_no_comma():
    assert normalize_instructor_key("Annie Witte") == "annie witte"


def test_key_collapses_whitespace():
    assert normalize_instructor_key("  Witte ,   Annie  ") == "annie witte"


def test_key_empty_for_blank():
    assert normalize_instructor_key("") == ""
    assert normalize_instructor_key(None) == ""


def test_key_preserves_periods_like_normalize_name():
    """pipeline.names.normalize_name keeps periods, so this must too — or the join
    silently matches nobody."""
    assert normalize_instructor_key("St. Onge, Marie") == "marie st. onge"
    assert normalize_instructor_key("Smith, John A.") == "john a. smith"


def test_key_unescapes_html_entities():
    """Banner HTML-escapes displayName exactly like courseTitle.

    Measured on the real Fall 2026 load: every apostrophe surname arrived as
    "O&#39;Connell", keyed as "brian o&#39;connell", and could never match the
    catalog's "brian o'connell" — 13 professors silently unmatched. The catalog
    side stores a real apostrophe (pipeline.names.normalize_name strips no
    punctuation), so the unescape has to happen here.
    """
    assert normalize_instructor_key("O&#39;Connell, Brian") == "brian o'connell"
    assert normalize_instructor_key("D&#39;Amico, Brian") == "brian d'amico"
    assert normalize_instructor_key("O&#39;Brien-Weiss, Meredith") == "meredith o'brien-weiss"


def test_key_unescapes_before_ascii_fold():
    """Order matters: unescaping after the NFKD/ascii step would leave a
    numeric entity for a non-ASCII character as literal digits in the key.
    "&#233;" is é, which must fold to "e" like test_key_strips_accents does.
    """
    assert normalize_instructor_key("Ram&#237;rez, Jos&#233;") == "jose ramirez"


def test_key_unescapes_ampersand_names():
    assert normalize_instructor_key("Smith &amp; Jones, Ada") == "ada smith & jones"


# ── clean_term_desc ──────────────────────────────────────────────────────

def test_clean_term_desc_drops_semester_suffix():
    assert clean_term_desc("Fall 2026 Semester") == "Fall 2026"


def test_clean_term_desc_drops_view_only_and_qualifier():
    assert clean_term_desc("Fall 2025 Law Semester (View Only)") == "Fall 2025"
    assert clean_term_desc("Spring 2026 CPS Quarter (View Only)") == "Spring 2026"


# ── parse_section ────────────────────────────────────────────────────────

def test_parse_section_unescapes_title():
    row = fixture("search_page.json")["data"][0]
    assert parse_section(row)["course_title"] == "Fin Accounting & Reporting"


def test_parse_section_maps_fields():
    got = parse_section(fixture("search_page.json")["data"][0])
    assert got["crn"] == "10324"
    assert got["term_code"] == "202710"
    assert got["term_desc"] == "Fall 2026"
    assert got["subject_course"] == "ACCT1201"
    assert got["section"] == "01"
    assert got["campus"] == "Boston"
    assert got["schedule_type"] == "Lecture"
    assert got["instructional_method"] == "Traditional"


# ── parse_faculty ────────────────────────────────────────────────────────

def test_parse_faculty_dedupes_one_person_across_blocks():
    got = parse_faculty(fixture("fmt_single.json"))
    assert len(got) == 1
    assert got[0]["instructor_key"] == "annie witte"
    assert got[0]["instructor_name"] == "Witte, Annie"
    assert got[0]["is_primary"] is True


def test_parse_faculty_ors_is_primary_across_blocks():
    """The docstring calls the OR load-bearing: primary in ANY block is
    primary. fmt_single.json has identical values in both blocks, so it cannot
    tell an OR from a plain overwrite — this makes the blocks disagree.
    """
    payload = {"fmt": [
        {"faculty": [{"displayName": "Witte, Annie", "primaryIndicator": True,
                      "emailAddress": None}]},
        {"faculty": [{"displayName": "Witte, Annie", "primaryIndicator": False,
                      "emailAddress": None}]},
    ]}
    got = parse_faculty(payload)
    assert len(got) == 1
    assert got[0]["is_primary"] is True, "a later non-primary block must not clear it"


def test_parse_faculty_drops_email_addresses():
    """Nothing uses them; they never leave the parser."""
    for f in parse_faculty(fixture("fmt_multi.json")):
        assert "instructor_email" not in f


def test_parse_faculty_picks_up_a_primary_flag_from_a_later_block():
    """The OR has to work in both directions — first block false, second true."""
    payload = {"fmt": [
        {"faculty": [{"displayName": "Witte, Annie", "primaryIndicator": False,
                      "emailAddress": None}]},
        {"faculty": [{"displayName": "Witte, Annie", "primaryIndicator": True,
                      "emailAddress": None}]},
    ]}
    assert parse_faculty(payload)[0]["is_primary"] is True


def test_parse_faculty_keeps_both_instructors():
    got = {f["instructor_key"]: f for f in parse_faculty(fixture("fmt_multi.json"))}
    assert set(got) == {"patrick hurley", "john a smith"}
    assert got["patrick hurley"]["is_primary"] is True
    assert got["john a smith"]["is_primary"] is False


def test_parse_faculty_empty_for_tba_section():
    assert parse_faculty(fixture("fmt_empty.json")) == []


def test_parse_faculty_tolerates_missing_keys():
    assert parse_faculty({}) == []
    assert parse_faculty({"fmt": [{}]}) == []


# ── section_end_dates ────────────────────────────────────────────────────

def test_section_end_dates_reads_meeting_times():
    rows = fixture("search_page.json")["data"]
    assert section_end_dates(rows) == [date(2026, 12, 20)]


def test_section_end_dates_empty_when_no_meetings():
    assert section_end_dates([{"meetingsFaculty": []}]) == []


# ── select_season ────────────────────────────────────────────────────────
# Banner suffixes closed terms with "(View Only)". Everything without it is
# open. Law/CPS ride on parallel codes and must all come along.

def test_select_season_picks_earliest_open_fall_spring():
    desc, codes = select_season(fixture("get_terms.json"))
    assert desc == "Fall 2026"
    assert codes == ["202710", "202715"]


def test_select_season_ignores_view_only():
    terms = [
        {"code": "202630", "description": "Spring 2026 Semester (View Only)"},
        {"code": "202710", "description": "Fall 2026 Semester"},
    ]
    assert select_season(terms) == ("Fall 2026", ["202710"])


def test_select_season_ignores_summer_and_winter():
    terms = [
        {"code": "202650", "description": "Summer 2026 Semester"},
        {"code": "202625", "description": "Winter 2027 CPS Quarter"},
        {"code": "202710", "description": "Fall 2026 Semester"},
    ]
    assert select_season(terms) == ("Fall 2026", ["202710"])


def test_select_season_prefers_earliest_open_season():
    # During Fall, Spring is often open too. The in-progress term wins.
    terms = [
        {"code": "202730", "description": "Spring 2027 Semester"},
        {"code": "202710", "description": "Fall 2026 Semester"},
    ]
    assert select_season(terms) == ("Fall 2026", ["202710"])


def test_select_season_raises_when_nothing_open():
    with pytest.raises(ValueError, match="no open Fall/Spring term"):
        select_season([{"code": "202610", "description": "Fall 2025 Semester (View Only)"}])


# ── parse_term ───────────────────────────────────────────────────────────
# Every season spelling getTerms used 2009-2026 (captured 2026-10-01).

@pytest.mark.parametrize("desc,label,season,group,year,track,closed", [
    ("Fall 2026 Semester", "Fall 2026", "Fall", "Fall", 2026, "Semester", False),
    ("Spring 2026 Semester (View Only)", "Spring 2026", "Spring", "Spring", 2026, "Semester", True),
    ("Summer Full 2025 Semester (View Only)", "Summer Full 2025", "Summer Full", "Summer", 2025, "Semester", True),
    ("Summer 1 2025 Semester (View Only)", "Summer 1 2025", "Summer 1", "Summer", 2025, "Semester", True),
    ("Summer 2 2025 Semester (View Only)", "Summer 2 2025", "Summer 2", "Summer", 2025, "Semester", True),
    ("Summer 2026 CPS Quarter (View Only)", "Summer 2026", "Summer", "Summer", 2026, "CPS Quarter", True),
    ("Winter 2026 CPS Quarter (View Only)", "Winter 2026", "Winter", "Winter", 2026, "CPS Quarter", True),
    ("Spring 2021 Law Quarter (View Only)", "Spring 2021", "Spring", "Spring", 2021, "Law Quarter", True),
])
def test_parse_term_reads_every_season_spelling(desc, label, season, group, year, track, closed):
    assert parse_term(desc) == {"label": label, "season": season, "season_group": group,
                                "year": year, "track": track, "view_only": closed}


def test_parse_term_rejects_what_it_cannot_read():
    assert parse_term("Something Banner renamed") is None
    assert parse_term(None) is None


# ── parse_section: history fields ────────────────────────────────────────
# search_history.json: two real searchResults rows captured 2026-10-01 — CS1100
# in Fall 2018 (closed, in person) and CS1200 in Fall 2026 (open, online).

def test_parse_section_reads_final_enrollment_and_credits():
    got = parse_section(fixture("search_history.json")["data"][0])
    assert got["enrollment"] == 19
    assert got["credit_hours_low"] == 4.0
    assert got["credit_hours_high"] is None
    assert got["instructional_method"] == "Hybrid"


def test_parse_section_online_section_credits():
    got = parse_section(fixture("search_history.json")["data"][1])
    assert got["credit_hours_low"] == 1.0


def test_parse_section_keeps_no_registration_data():
    """Seats, waitlists, meeting times, rooms, section links and NUpath
    attributes are SearchNEU's job — the parser never carries them."""
    got = parse_section(fixture("search_history.json")["data"][0])
    for gone in ("max_enrollment", "wait_count", "wait_capacity", "meetings",
                 "attributes", "is_linked", "link_identifier", "cross_list",
                 "part_of_term"):
        assert gone not in got


def test_parse_section_tolerates_missing_counts():
    got = parse_section({"courseReferenceNumber": "1", "enrollment": None})
    assert got["enrollment"] is None
