"""Season scrape: fan-out and the gates that refuse to write.

Every gate here exists because the failure it catches is silent. A Banner change
that halves the section count looks exactly like a quiet semester unless
something compares the numbers.
"""
import json
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
import banner_scrape  # noqa: E402
from banner_client import Roster  # noqa: E402
from banner_scrape import (SanityGateFailed, plan_terms,  # noqa: E402
                           scrape_season, scrape_term)


def section(crn, subject_course="ACCT1201", schedule_type="Lecture",
            campus="Boston", end="12/20/2026"):
    return {
        "term": "202710", "termDesc": "Fall 2026 Semester",
        "courseReferenceNumber": crn, "subject": subject_course[:4],
        "subjectCourse": subject_course, "courseNumber": subject_course[4:],
        "sequenceNumber": "01", "courseTitle": "T", "campusDescription": campus,
        "instructionalMethodDescription": "Traditional",
        "scheduleTypeDescription": schedule_type,
        "meetingsFaculty": [{"meetingTime": {"endDate": end}}],
    }


_NO_ROSTER = object()  # sentinel: distinct from roster=None, which means "request failed"


class FakeClient:
    """Stands in for BannerClient with no transport at all."""

    def __init__(self, sections, faculty, roster=_NO_ROSTER, terms=None):
        self._sections = sections
        self._faculty = faculty
        self._roster = roster
        self.terms = terms or [{"code": "202710", "description": "Fall 2026 Semester"}]
        self.bootstrapped = []
        self.faculty_calls = []
        self.retry_calls = []

    def get_terms(self):
        return self.terms

    def bootstrap(self, term_code):
        self.bootstrapped.append(term_code)

    def iter_sections(self, term_code):
        return iter(self._sections.get(term_code, []))

    def faculty_for_many(self, term_code, crns):
        self.faculty_calls.extend(crns)
        return {c: self._faculty.get(c) for c in crns}

    def faculty_for(self, term_code, crn):
        self.retry_calls.append(crn)
        return self._faculty.get(crn)

    def instructor_roster(self, term_code):
        # Mirrors BannerClient: a Roster(keys, row_count), or None on transport
        # failure. row_count defaults to len(keys) — the tests that care about
        # the two differing pass a Roster in directly.
        if self._roster is _NO_ROSTER:
            return Roster(keys=set(), row_count=0)
        if self._roster is None or isinstance(self._roster, Roster):
            return self._roster
        return Roster(keys=self._roster, row_count=len(self._roster))


ANNIE = [{"instructor_name": "Witte, Annie", "instructor_key": "annie witte",
          "instructor_email": None, "is_primary": True}]
PAT = [{"instructor_name": "Hurley, Patrick", "instructor_key": "patrick hurley",
        "instructor_email": "hurley.pa@northeastern.edu", "is_primary": True}]
TODAY = date(2026, 8, 4)


def test_scrape_term_joins_sections_to_instructors():
    client = FakeClient({"202710": [section("1"), section("2", "CS3000")]},
                        {"1": ANNIE, "2": PAT})
    got = scrape_term(client, "202710", today=TODAY)
    assert {(r["crn"], r["instructor_key"]) for r in got["instructors"]} == {
        ("1", "annie witte"), ("2", "patrick hurley")}
    assert {(s["crn"], s["subject_course"]) for s in got["sections"]} == {
        ("1", "ACCT1201"), ("2", "CS3000")}


def test_scrape_term_emits_one_row_per_instructor():
    two = ANNIE + PAT
    client = FakeClient({"202710": [section("1")]}, {"1": two})
    assert len(scrape_term(client, "202710", today=TODAY)["instructors"]) == 2


def test_scrape_term_keeps_tba_sections_without_instructor_rows():
    """~13% of sections are TBA. Nobody can be attributed, but the section
    still counts toward class size and when the course is offered."""
    client = FakeClient({"202710": [section("1"), section("2")]}, {"1": ANNIE, "2": []})
    got = scrape_term(client, "202710", today=TODAY)
    assert sorted(s["crn"] for s in got["sections"]) == ["1", "2"]
    assert [r["crn"] for r in got["instructors"]] == ["1"]
    assert got["stats"] == {"section_count": 2, "attributed_sections": 1,
                            "instructor_count": 1}


def test_instructor_rows_carry_their_term_code():
    client = FakeClient({"202710": [section("1")]}, {"1": ANNIE})
    got = scrape_term(client, "202710", today=TODAY)
    assert got["instructors"][0]["term_code"] == "202710"


# ── unattributed-section counter ──────────────────────────────────────────
# Dropped TBA sections are invisible everywhere else: banner_unmatched records
# unmatched *instructors*, so a section nobody is assigned to leaves nothing
# behind. Measured on the real Fall 2026 load: 1,134 of 9,505 sections (11.9%), and
# 229 of 3,180 courses had no instructor on any section. A professor who teaches
# three sections with one listed TBA gets a chip showing two — quieter than a
# missing chip, and nothing counts it. This line is the only signal that the
# number moved.

def test_scrape_term_reports_unattributed_sections(capsys):
    client = FakeClient({"202710": [section("1"), section("2"), section("3")]},
                        {"1": ANNIE, "2": [], "3": []})
    scrape_term(client, "202710", today=TODAY)
    out = capsys.readouterr().out
    assert "2 of 3 teaching sections unattributed" in out
    assert "2 TBA" in out


def test_unattributed_counter_separates_tba_from_lookup_failure(capsys):
    """[] (Banner assigned nobody) and None (the lookup broke) are different
    problems: TBA moving is a staffing fact, failures moving is a scraper bug.
    A single total would hide one behind the other.
    """
    sections = [section(str(i)) for i in range(200)]
    faculty = {str(i): (None if i < 2 else ([] if i < 20 else ANNIE))
               for i in range(200)}
    client = FakeClient({"202710": sections}, faculty)
    scrape_term(client, "202710", today=TODAY)
    out = capsys.readouterr().out
    assert "20 of 200 teaching sections unattributed" in out
    assert "18 TBA" in out
    assert "2 lookup failures" in out


def test_unattributed_counter_prints_zero_when_everything_is_attributed(capsys):
    """Printed every run, not only when non-zero — a line that appears and
    disappears is one an operator can't diff against the previous run."""
    client = FakeClient({"202710": [section("1")]}, {"1": ANNIE})
    scrape_term(client, "202710", today=TODAY)
    assert "0 of 1 teaching sections unattributed" in capsys.readouterr().out


def test_unattributed_counter_prints_before_the_drop_gate_aborts(capsys):
    """Same reasoning as check_match_gate's ordering: an operator diagnosing a
    failed run needs the numbers, and a gate that raises first hides them.
    (The section-drop gate needs no counter — it fires before any lookup.)"""
    client = FakeClient({"202710": [section(str(i)) for i in range(70)]},
                        {str(i): [] for i in range(70)})
    with pytest.raises(SanityGateFailed, match="no instructor could be attributed"):
        scrape_term(client, "202710", today=TODAY)
    assert "70 of 70 teaching sections unattributed" in capsys.readouterr().out


def test_scrape_term_keeps_individual_instruction_rows():
    """The section row is stored; its instructor is never looked up."""
    client = FakeClient(
        {"202710": [section("1", "CS7999", schedule_type="Individual Instruction"),
                    section("2")]},
        {"1": ANNIE, "2": PAT})
    got = scrape_term(client, "202710", today=TODAY)
    by_crn = {s["crn"]: s for s in got["sections"]}
    assert by_crn["1"]["schedule_type"] == "Individual Instruction"
    assert [r["crn"] for r in got["instructors"]] == ["2"]


def test_scrape_term_fetches_every_crn_every_run():
    """No cache: a CRN already seen in a previous run is fetched again, because a
    cached result can silently outlive an instructor reassignment."""
    client = FakeClient({"202710": [section("1"), section("2")]}, {"1": ANNIE, "2": PAT})
    got = scrape_term(client, "202710", today=TODAY)
    assert sorted(client.faculty_calls) == ["1", "2"]
    assert client.retry_calls == []
    assert len(got["instructors"]) == 2


def test_non_teaching_sections_are_stored_but_never_looked_up(capsys):
    """~20% of a term is Individual Instruction; looking those up buys nothing."""
    client = FakeClient(
        {"202710": [section("1"), section("2", "CS7990", schedule_type="Individual Instruction"),
                    section("3", "COOP3945", schedule_type="COOP Placement")]},
        {"1": ANNIE, "2": PAT, "3": PAT})
    got = scrape_term(client, "202710", today=TODAY)
    assert client.faculty_calls == ["1"]
    assert sorted(s["crn"] for s in got["sections"]) == ["1", "2", "3"]
    assert [r["crn"] for r in got["instructors"]] == ["1"]
    assert "2 non-teaching sections not looked up" in capsys.readouterr().out


def test_sections_only_scrape_makes_no_faculty_or_roster_requests():
    client = FakeClient({"202510": [section("1"), section("2")]}, {"1": ANNIE},
                        roster=None)   # would fail the roster gate if it were asked
    got = scrape_term(client, "202510", today=TODAY, view_only=True,
                      with_instructors=False)
    assert client.faculty_calls == []
    assert got["instructors"] is None
    assert got["stats"]["section_count"] == 2


def test_sections_only_scrape_still_gates_on_a_section_drop():
    client = FakeClient({"202510": [section("1")]}, {})
    with pytest.raises(SanityGateFailed, match="section count dropped"):
        scrape_term(client, "202510", previous_count=100, today=TODAY,
                    view_only=True, with_instructors=False)


def test_failed_lookups_get_one_sequential_retry():
    """The concurrent pass is where transient failures land; a quieter second
    pass recovers them before the failure gate counts anything."""
    client = FakeClient({"202710": [section("1"), section("2")]}, {"1": ANNIE, "2": PAT})
    client.faculty_for_many = lambda term, crns: (
        client.faculty_calls.extend(crns) or {"1": ANNIE, "2": None})
    got = scrape_term(client, "202710", today=TODAY)
    assert client.retry_calls == ["2"]
    assert {r["crn"] for r in got["instructors"]} == {"1", "2"}


def test_gate_aborts_on_zero_sections():
    client = FakeClient({"202710": []}, {})
    with pytest.raises(SanityGateFailed, match="0 sections returned"):
        scrape_term(client, "202710", today=TODAY)


def test_gate_aborts_when_section_count_drops_more_than_20_percent():
    client = FakeClient({"202710": [section(str(i)) for i in range(70)]},
                        {str(i): ANNIE for i in range(70)})
    with pytest.raises(SanityGateFailed, match="section count dropped"):
        scrape_term(client, "202710", previous_count=100, today=TODAY)
    assert client.faculty_calls == []     # refused before ~70 wasted lookups


def test_gate_allows_a_small_drop():
    client = FakeClient({"202710": [section(str(i)) for i in range(95)]},
                        {str(i): ANNIE for i in range(95)})
    got = scrape_term(client, "202710", previous_count=100, today=TODAY)
    assert got["stats"]["section_count"] == 95


def test_drop_gate_counts_tba_sections_on_both_sides():
    """previous_count is banner_terms.section_count, which includes TBA
    sections, so this run's count must include them too. 90 sections of which
    30 are TBA is a 10% drop from 100, not a 40% one."""
    sections = [section(str(i)) for i in range(90)]
    faculty = {str(i): (ANNIE if i < 60 else []) for i in range(90)}
    client = FakeClient({"202710": sections}, faculty)
    got = scrape_term(client, "202710", previous_count=100, today=TODAY)
    assert got["stats"]["section_count"] == 90


def test_gate_aborts_when_no_section_has_an_instructor():
    """Sections present, every faculty lookup empty — a response-shape change.

    Distinct from the zero-sections gate (which fires before the join) and from
    the failure-ratio gate (which only counts None, not []). Without this, the
    run returns nothing and reports success.
    """
    sections = [section(str(i)) for i in range(10)]
    client = FakeClient({"202710": sections}, {str(i): [] for i in range(10)})
    with pytest.raises(SanityGateFailed, match="no instructor could be attributed"):
        scrape_term(client, "202710", today=TODAY)


def test_gate_aborts_when_instructors_are_far_below_the_roster():
    """The independent check on pagination and resetDataForm."""
    client = FakeClient({"202710": [section("1")]}, {"1": ANNIE},
                        roster={f"person {i}" for i in range(50)})
    with pytest.raises(SanityGateFailed, match="roster"):
        scrape_term(client, "202710", today=TODAY)


def test_gate_aborts_when_roster_request_fails():
    """instructor_roster returns None on transport failure — that must abort,
    not silently be treated as "Banner reports zero instructors" (which would
    just skip the comparison and hide a coordinated Banner change)."""
    client = FakeClient({"202710": [section("1")]}, {"1": ANNIE}, roster=None)
    with pytest.raises(SanityGateFailed, match="roster request failed"):
        scrape_term(client, "202710", today=TODAY)


def test_gate_allows_a_legitimately_empty_roster():
    """roster=set() (Banner genuinely reports nobody) is not a transport
    failure and must not abort — there's just nothing to compare against."""
    client = FakeClient({"202710": [section("1")]}, {"1": ANNIE}, roster=set())
    assert len(scrape_term(client, "202710", today=TODAY)["instructors"]) == 1


def test_gate_aborts_when_roster_hits_the_request_cap():
    """get_instructor's own max=6000 is a hard request cap, not a real limit
    on term size. A roster at or above it was truncated, so the ratio
    comparison against `found` would be meaningless — must abort instead."""
    client = FakeClient({"202710": [section("1")]}, {"1": ANNIE},
                        roster={f"person {i}" for i in range(6000)})
    with pytest.raises(SanityGateFailed, match="request cap"):
        scrape_term(client, "202710", today=TODAY)


def test_gate_catches_a_truncated_roster_whose_rows_collapse_on_dedup():
    """The cap is on ROWS. A roster truncated at exactly 6000 rows that
    contains any duplicate name yields fewer than 6000 distinct keys, so a
    set-size comparison would wave it through — and then compare `found`
    against a silently truncated roster."""
    client = FakeClient(
        {"202710": [section("1")]}, {"1": ANNIE},
        roster=Roster(keys={f"person {i}" for i in range(5990)}, row_count=6000))
    with pytest.raises(SanityGateFailed, match="request cap"):
        scrape_term(client, "202710", today=TODAY)


def test_gate_aborts_when_faculty_calls_fail_too_often():
    sections = [section(str(i)) for i in range(100)]
    faculty = {str(i): (None if i < 10 else ANNIE) for i in range(100)}
    client = FakeClient({"202710": sections}, faculty)
    with pytest.raises(SanityGateFailed, match="faculty lookups failed"):
        scrape_term(client, "202710", today=TODAY)


def test_gate_aborts_when_failures_exceed_the_ratio_on_the_full_fetch_set():
    """200 sections, 10 None results (5%) is well past the 2% ratio and past the
    MIN_FACULTY_FAILURES_TOLERATED=3 floor — must abort."""
    sections = [section(str(i)) for i in range(200)]
    faculty = {str(i): (None if i < 10 else ANNIE) for i in range(200)}
    client = FakeClient({"202710": sections}, faculty)
    with pytest.raises(SanityGateFailed, match="faculty lookups failed"):
        scrape_term(client, "202710", today=TODAY)


def test_gate_allows_a_small_number_of_failures_on_the_full_fetch_set():
    """200 sections, 2 None results is below both the ratio (2% of 200 = 4) and
    the MIN_FACULTY_FAILURES_TOLERATED=3 floor — must not abort."""
    sections = [section(str(i)) for i in range(200)]
    faculty = {str(i): (None if i < 2 else ANNIE) for i in range(200)}
    client = FakeClient({"202710": sections}, faculty)
    got = scrape_term(client, "202710", today=TODAY)
    assert len(got["instructors"]) == 198
    assert got["stats"]["section_count"] == 200


def test_gate_aborts_when_term_already_ended():
    """Validates Banner's (View Only) convention against real meeting dates."""
    client = FakeClient({"202710": [section("1", end="12/20/2025")]}, {"1": ANNIE})
    with pytest.raises(SanityGateFailed, match="already ended"):
        scrape_term(client, "202710", today=TODAY)


def test_end_date_gate_is_skipped_for_a_closed_term():
    """A View Only term ended long ago by definition — that's what backfill is for."""
    client = FakeClient({"201910": [section("1", end="12/05/2018")]}, {"1": ANNIE})
    got = scrape_term(client, "201910", today=TODAY, view_only=True)
    assert got["stats"]["section_count"] == 1


def test_scrape_season_covers_every_sibling_term():
    """Law and CPS ride on parallel codes; missing them hides those professors."""
    terms = [{"code": "202710", "description": "Fall 2026 Semester"},
             {"code": "202715", "description": "Fall 2026 CPS Quarter"},
             {"code": "202630", "description": "Spring 2026 Semester (View Only)"}]
    client = FakeClient(
        {"202710": [section("1")], "202715": [section("9", "LAW1000")]},
        {"1": ANNIE, "9": PAT}, terms=terms)
    desc, scrapes = scrape_season(client, today=TODAY)
    assert desc == "Fall 2026"
    assert client.bootstrapped == ["202710", "202715"]
    assert {r["crn"] for s in scrapes.values() for r in s["instructors"]} == {"1", "9"}


def test_scrape_season_bootstraps_before_each_term():
    terms = [{"code": "202710", "description": "Fall 2026 Semester"}]
    client = FakeClient({"202710": [section("1")]}, {"1": ANNIE}, terms=terms)
    scrape_season(client, today=TODAY)
    assert client.bootstrapped == ["202710"]


# ── CLI ───────────────────────────────────────────────────────────────────

def test_dry_run_does_not_write_the_json_output(tmp_path, monkeypatch):
    """--dry-run promises "write nothing" in both the usage docstring and its
    own --help text. It has to actually gate the one write main() can do."""
    out = tmp_path / "rows.json"
    client = FakeClient({"202710": [section("1")]}, {"1": ANNIE})
    monkeypatch.setattr(banner_scrape, "BannerClient", lambda: client)

    assert banner_scrape.main(
        ["--term", "202710", "--json-out", str(out), "--dry-run"]) == 0
    assert not out.exists()


def test_json_out_writes_when_not_a_dry_run(tmp_path, monkeypatch):
    out = tmp_path / "rows.json"
    client = FakeClient({"202710": [section("1")]}, {"1": ANNIE})
    monkeypatch.setattr(banner_scrape, "BannerClient", lambda: client)

    assert banner_scrape.main(["--term", "202710", "--json-out", str(out)]) == 0
    written = json.loads(out.read_text())
    assert written["term_desc"] == "Fall 2026"
    assert len(written["terms"]["202710"]["instructors"]) == 1


# ── plan_terms ────────────────────────────────────────────────────────────

TERMS = [
    {"code": "202710", "description": "Fall 2026 Semester"},
    {"code": "202650", "description": "Summer 2026 Semester (View Only)"},
    {"code": "202630", "description": "Spring 2026 Semester (View Only)"},
    {"code": "202615", "description": "Fall 2025 CPS Quarter (View Only)"},
    {"code": "201510", "description": "Fall 2014 Semester (View Only)"},
    {"code": "999999", "description": "Something Banner renamed"},
]


def test_plan_current_picks_every_open_term():
    assert [c for c, _ in plan_terms(TERMS, {}, "current")] == ["202710"]


def test_plan_backfill_takes_closed_terms_newest_first_from_since():
    got = [c for c, _ in plan_terms(TERMS, {}, "backfill", since_term="201610")]
    assert got == ["202650", "202630", "202615"]


def test_plan_backfill_skips_terms_already_scraped_after_closing():
    got = plan_terms(TERMS, {"202650": True, "202630": True}, "backfill", "201610")
    assert [c for c, _ in got] == ["202615"]


def test_plan_backfill_rescrapes_a_term_last_seen_open():
    """Its enrollment was a mid-registration snapshot; the final headcount is
    only on the closed term."""
    got = plan_terms(TERMS, {"202650": False, "202630": True, "202615": True},
                     "backfill", "201610")
    assert [c for c, _ in got] == ["202650"]


def test_plan_skips_unparseable_terms_rather_than_guessing():
    assert "999999" not in [c for c, _ in plan_terms(TERMS, {}, "current")]


def test_plan_backfill_since_is_a_term_code_not_a_calendar_year():
    """--since 202210 must start at Fall 2021 and leave out Spring and Summer
    2021, which a calendar-year filter of 2021 would have pulled in."""
    terms = [{"code": "202210", "description": "Fall 2021 Semester (View Only)"},
             {"code": "202150", "description": "Summer Full 2021 Semester (View Only)"},
             {"code": "202130", "description": "Spring 2021 Semester (View Only)"}]
    assert [c for c, _ in plan_terms(terms, {}, "backfill", "202210")] == ["202210"]


def test_plan_rejects_an_unknown_mode():
    with pytest.raises(ValueError):
        plan_terms(TERMS, {}, "everything")
