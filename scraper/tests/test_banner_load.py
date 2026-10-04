"""Loader behaviour against a real sqlite database.

The logic under test is SQL, so a fake cursor would assert nothing — nothing
is gained by mocking it.
"""
import os
import sqlite3
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import psycopg2  # noqa: E402

import banner_scrape  # noqa: E402
import load_banner_to_crdb  # noqa: E402
from banner_client import BannerRequestFailed  # noqa: E402
from load_banner_to_crdb import (apply_ddl, connect, known_terms,  # noqa: E402
                                 push, run, sync_view_only, with_retry,
                                 write_term)
from test_banner_scrape import ANNIE, PAT, FakeClient, section  # noqa: E402

FALL = {"label": "Fall 2026", "season": "Fall", "season_group": "Fall",
        "year": 2026, "track": "Semester", "view_only": False}
SPRING = {"label": "Spring 2026", "season": "Spring", "season_group": "Spring",
          "year": 2026, "track": "Semester", "view_only": True}


@pytest.fixture
def cur():
    conn = sqlite3.connect(":memory:")
    c = conn.cursor()
    apply_ddl(c)
    return c


def sec(crn, course="ACCT1201", enrollment=30):
    return {"crn": crn, "subject": course[:4], "subject_course": course,
            "course_number": course[4:], "section": "01", "course_title": "T",
            "campus": "Boston", "instructional_method": "Traditional",
            "schedule_type": "Lecture", "enrollment": enrollment,
            "max_enrollment": 40}


def ins(term, crn, key="annie witte"):
    return {"term_code": term, "crn": crn, "instructor_key": key,
            "instructor_name": key.title(), "instructor_email": None,
            "is_primary": True}


def scrape(sections, instructors):
    return {"sections": sections, "instructors": instructors,
            "stats": {"section_count": len(sections),
                      "attributed_sections": len({i["crn"] for i in instructors}),
                      "instructor_count": len({i["instructor_key"] for i in instructors})}}


def count(cur, table, term=None):
    if term:
        return cur.execute(f"SELECT count(*) FROM {table} WHERE term_code = ?",
                           (term,)).fetchone()[0]
    return cur.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# ── write_term ────────────────────────────────────────────────────────────

def test_write_term_stores_sections_instructors_and_counts(cur):
    write_term(cur, "202710", FALL, "Fall 2026 Semester",
               scrape([sec("1"), sec("2")], [ins("202710", "1")]))
    assert count(cur, "banner_sections") == 2
    assert count(cur, "banner_section_instructors") == 1
    row = cur.execute("SELECT term_label, season_group, view_only, scraped_closed, "
                      "section_count, attributed_sections, instructors_source "
                      "FROM banner_terms").fetchone()
    assert row == ("Fall 2026", "Fall", 0, 0, 2, 1, "banner")
    assert cur.execute("SELECT source FROM banner_section_instructors").fetchone() == ("banner",)


def test_write_term_keeps_tba_sections(cur):
    """A section nobody teaches yet still has a size and a term."""
    write_term(cur, "202710", FALL, None, scrape([sec("1"), sec("2")], [ins("202710", "1")]))
    assert {r[0] for r in cur.execute("SELECT crn FROM banner_sections")} == {"1", "2"}


def test_rewriting_a_term_drops_cancelled_sections_and_reassigned_instructors(cur):
    """The whole term is replaced, which covers every case the old per-CRN
    and per-pair prune handled: a cancelled section, a reassignment from A to
    B, and a key that changed spelling."""
    write_term(cur, "202710", FALL, None,
               scrape([sec("1"), sec("2")], [ins("202710", "1"), ins("202710", "2")]))
    write_term(cur, "202710", FALL, None,
               scrape([sec("1")], [ins("202710", "1", "patrick hurley")]))
    assert {r[0] for r in cur.execute("SELECT crn FROM banner_sections")} == {"1"}
    assert [r[0] for r in cur.execute(
        "SELECT instructor_key FROM banner_section_instructors")] == ["patrick hurley"]


def test_writing_one_term_never_touches_another(cur):
    """History accumulates: the old loader deleted every other season."""
    write_term(cur, "202630", SPRING, None, scrape([sec("7")], [ins("202630", "7")]))
    write_term(cur, "202710", FALL, None, scrape([sec("1")], [ins("202710", "1")]))
    write_term(cur, "202710", FALL, None, scrape([sec("1")], [ins("202710", "1")]))
    assert count(cur, "banner_sections", "202630") == 1
    assert count(cur, "banner_section_instructors", "202630") == 1
    assert count(cur, "banner_terms") == 2


def test_co_taught_section_keeps_both_instructors(cur):
    write_term(cur, "202710", FALL, None, scrape(
        [sec("1")], [ins("202710", "1"), ins("202710", "1", "patrick hurley")]))
    assert count(cur, "banner_section_instructors") == 2


def test_known_terms_reports_closed_flag_and_baseline(cur):
    write_term(cur, "202630", SPRING, None, scrape([sec("7"), sec("8")], []))
    write_term(cur, "202710", FALL, None, scrape([sec("1")], []))
    assert known_terms(cur) == {"202630": (True, 2), "202710": (False, 1)}


def test_sections_only_write_leaves_existing_instructor_rows_alone(cur):
    """A sections-only re-scrape of an import-filled term must not wipe
    its instructors, or the term's source label."""
    write_term(cur, "202510", SPRING, None, scrape([sec("1")], [ins("202510", "1")]))
    cur.execute("UPDATE banner_section_instructors SET source = 'import'")
    cur.execute("UPDATE banner_terms SET instructors_source = 'import'")
    write_term(cur, "202510", SPRING, None,
               {"sections": [sec("1"), sec("2")], "instructors": None,
                "stats": {"section_count": 2, "attributed_sections": 0, "instructor_count": 0}})
    assert count(cur, "banner_sections") == 2
    assert cur.execute("SELECT source FROM banner_section_instructors").fetchall() == [("import",)]
    assert cur.execute("SELECT instructors_source FROM banner_terms").fetchone() == ("import",)


def test_sections_only_write_of_a_new_term_has_no_source_yet(cur):
    write_term(cur, "202510", SPRING, None,
               {"sections": [sec("1")], "instructors": None,
                "stats": {"section_count": 1, "attributed_sections": 0, "instructor_count": 0}})
    assert cur.execute("SELECT instructors_source FROM banner_terms").fetchone() == ("none",)


def test_first_seen_is_set_once_for_open_terms_and_never_for_backfill(cur):
    write_term(cur, "202710", FALL, None, scrape([sec("1")], []))
    first = cur.execute("SELECT first_seen_at FROM banner_terms WHERE term_code='202710'").fetchone()[0]
    assert first
    write_term(cur, "202710", FALL, None, scrape([sec("1")], []))
    assert cur.execute("SELECT first_seen_at FROM banner_terms WHERE term_code='202710'").fetchone()[0] == first
    write_term(cur, "202630", SPRING, None, scrape([sec("7")], []))
    assert cur.execute("SELECT first_seen_at FROM banner_terms WHERE term_code='202630'").fetchone()[0] is None


def test_a_failed_lookup_keeps_the_rows_last_week_attributed(cur):
    """The reviewer's repro: CRN 2's lookup failed on the final scrape, the gate
    tolerated it, and the delete wiped the instructor last week had right."""
    write_term(cur, "202710", FALL, None,
               scrape([sec("1"), sec("2")], [ins("202710", "1"), ins("202710", "2", "pat hurley")]))
    final = scrape([sec("1"), sec("2")], [ins("202710", "1")])
    final["failed_crns"] = ["2"]
    write_term(cur, "202710", {**FALL, "view_only": True}, None, final)
    assert sorted(cur.execute("SELECT crn, instructor_key FROM banner_section_instructors")) == [
        ("1", "annie witte"), ("2", "pat hurley")]


def test_a_closed_term_with_failed_lookups_is_not_marked_finished(cur):
    """So the next finalize pass retries it rather than freezing the gap."""
    final = scrape([sec("1"), sec("2")], [ins("202630", "1")])
    final["failed_crns"] = ["2"]
    write_term(cur, "202630", SPRING, None, final)
    assert known_terms(cur)["202630"] == (False, 2)


def test_an_ended_term_is_stored_closed(cur):
    ended = scrape([sec("1")], [ins("202650", "1")])
    ended["ended"] = True
    write_term(cur, "202650", {**FALL, "label": "Summer 2026"}, None, ended)
    assert cur.execute("SELECT view_only, scraped_closed FROM banner_terms").fetchone() == (1, 1)


def test_sections_only_write_keeps_the_terms_instructor_counts(cur):
    write_term(cur, "202510", SPRING, None,
               scrape([sec("1"), sec("2")], [ins("202510", "1"), ins("202510", "2", "pat hurley")]))
    write_term(cur, "202510", SPRING, None,
               {"sections": [sec("1"), sec("2")], "instructors": None,
                "stats": {"section_count": 2, "attributed_sections": 0, "instructor_count": 0}})
    assert cur.execute("SELECT attributed_sections, instructor_count FROM banner_terms").fetchone() == (2, 2)


def test_roster_duplicates_are_stored_and_replaced_with_the_term(cur):
    first = scrape([sec("1")], [ins("202710", "1")])
    first["roster_duplicates"] = ["wei wang"]
    write_term(cur, "202710", FALL, None, first)
    assert cur.execute("SELECT instructor_key FROM banner_roster_duplicates").fetchall() == [("wei wang",)]
    write_term(cur, "202710", FALL, None, scrape([sec("1")], [ins("202710", "1")]))
    assert count(cur, "banner_roster_duplicates") == 0


# ── sync_view_only ────────────────────────────────────────────────────────

def test_sync_marks_a_closed_term_without_clearing_its_final_scrape_debt(cur):
    """The chip must stop naming last term at once, but the backfill still
    owes that term a final scrape — scraped_closed stays false until then."""
    write_term(cur, "202710", FALL, None, scrape([sec("1")], []))
    n = sync_view_only(cur, [{"code": "202710", "description": "Fall 2026 Semester (View Only)"}])
    assert n == 1
    assert cur.execute("SELECT view_only, scraped_closed FROM banner_terms").fetchone() == (1, 0)
    assert known_terms(cur)["202710"] == (False, 1)


def test_sync_leaves_open_terms_alone(cur):
    write_term(cur, "202710", FALL, None, scrape([sec("1")], []))
    assert sync_view_only(cur, [{"code": "202710", "description": "Fall 2026 Semester"}]) == 0


# ── run ───────────────────────────────────────────────────────────────────

TERMS = [{"code": "202710", "description": "Fall 2026 Semester"},
         {"code": "202630", "description": "Spring 2026 Semester (View Only)"},
         {"code": "202610", "description": "Fall 2025 Semester (View Only)"}]


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "banner.db")
    return lambda: sqlite3.connect(path)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    class _Date(date):
        @classmethod
        def today(cls):
            return date(2026, 10, 1)
    monkeypatch.setattr(banner_scrape, "date", _Date)


def test_run_current_loads_only_open_terms(db):
    client = FakeClient({"202710": [section("1")], "202630": [section("5")]},
                        {"1": ANNIE, "5": PAT}, terms=TERMS)
    assert run(client, db, "current") == (["202710"], [])
    assert count(db().cursor(), "banner_sections") == 1


def test_run_current_carries_on_past_a_refused_newer_term(db, capsys):
    """The reviewer's repro: a future term with no sections yet sorts above the
    live term, and the old `break` meant Fall 2026 was never refreshed."""
    terms = [{"code": "202730", "description": "Spring 2027 Semester"}] + TERMS
    client = FakeClient({"202730": [], "202710": [section("1")]}, {"1": ANNIE}, terms=terms)
    assert run(client, db, "current") == (["202710"], ["202730"])
    assert count(db().cursor(), "banner_sections", "202710") == 1


def test_run_current_treats_a_failed_bootstrap_as_one_refused_term(db):
    class FlakyBootstrap(FakeClient):
        def bootstrap(self, term_code):
            if term_code == "202730":
                raise BannerRequestFailed("term/search failed (500)")
            super().bootstrap(term_code)

    terms = [{"code": "202730", "description": "Spring 2027 Semester"}] + TERMS
    client = FlakyBootstrap({"202710": [section("1")]}, {"1": ANNIE}, terms=terms)
    assert run(client, db, "current") == (["202710"], ["202730"])


def test_run_current_skips_a_term_already_stored_as_ended(db):
    """Once an ended term is stored closed, the weekly run stops re-scraping it
    while Banner still lists it as open."""
    client = FakeClient({"202710": [section("1", end="09/01/2026")]}, {"1": ANNIE}, terms=TERMS)
    assert run(client, db, "current") == (["202710"], [])
    assert known_terms(db().cursor())["202710"] == (True, 1)
    assert run(client, db, "current") == ([], [])


def test_run_backfill_is_resumable_and_skips_finished_terms(db):
    client = FakeClient({"202630": [section("5")], "202610": [section("6")]},
                        {"5": ANNIE, "6": PAT}, terms=TERMS)
    assert run(client, db, "backfill", since_term="202610", instructors_from="202610", max_sections=1) == (["202630"], [])
    assert run(client, db, "backfill", since_term="202610", instructors_from="202610") == (["202610"], [])
    assert run(client, db, "backfill", since_term="202610", instructors_from="202610") == ([], [])


def test_run_backfill_skips_a_gated_term_and_carries_on(db, capsys):
    client = FakeClient({"202630": [], "202610": [section("6")]}, {"6": PAT}, terms=TERMS)
    assert run(client, db, "backfill", since_term="202610", instructors_from="202610") == (["202610"], ["202630"])
    assert "0 sections returned" in capsys.readouterr().err


def test_run_backfill_is_sections_only_before_instructors_from(db):
    client = FakeClient({"202630": [section("5")], "202610": [section("6")]},
                        {"5": ANNIE, "6": PAT}, terms=TERMS)
    run(client, db, "backfill", since_term="202610", instructors_from="202630")
    assert client.faculty_calls == ["5"]
    cur = db().cursor()
    assert dict(cur.execute("SELECT term_code, instructors_source FROM banner_terms")) == {
        "202630": "banner", "202610": "none"}


def test_push_copies_a_staged_file_and_is_idempotent(db, tmp_path):
    stage = str(tmp_path / "stage.db")
    client = FakeClient({"202710": [section("1")], "202630": [section("5")]},
                        {"1": ANNIE, "5": PAT}, terms=TERMS)
    run(client, lambda: sqlite3.connect(stage), "current")
    run(client, lambda: sqlite3.connect(stage), "backfill", since_term="202630",
        instructors_from="202630")
    push(stage, db)
    push(stage, db)
    cur = db().cursor()
    assert count(cur, "banner_terms") == 2
    assert count(cur, "banner_sections") == 2
    assert count(cur, "banner_section_instructors") == 2


def test_run_dry_run_writes_no_rows(db):
    client = FakeClient({"202710": [section("1")]}, {"1": ANNIE}, terms=TERMS)
    assert run(client, db, "current", dry_run=True) == (["202710"], [])
    assert count(db().cursor(), "banner_sections") == 0


# CockroachDB runs SERIALIZABLE, so a write that overlaps the live site's
# reads can be aborted with 40001 and has to be replayed by the client.
# load_evidence_to_crdb.py learned this the hard way; these pin the same behaviour for the Banner write path.

class _FakeConn:
    """One connection attempt. Raises on the statements it was told to."""

    def __init__(self, raise_on_commit=None):
        self._raise_on_commit = raise_on_commit
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self

    def execute(self, *_a, **_kw):
        return None

    def commit(self):
        if self._raise_on_commit:
            exc, self._raise_on_commit = self._raise_on_commit, None
            raise exc
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_with_retry_replays_the_whole_transaction_on_40001():
    """The unit of replay is the transaction, not the statement: a retried
    upsert that skipped its prune would leave the table half-updated."""
    conns = [_FakeConn(raise_on_commit=psycopg2.errors.SerializationFailure()),
             _FakeConn()]
    ran = []
    slept = []

    def work(_cur):
        ran.append("work")
        return "done"

    result = with_retry(lambda: conns.pop(0), work, sleep=slept.append)
    assert result == "done"
    assert ran == ["work", "work"], "the work must be re-run, not just re-committed"
    assert len(slept) == 1


def test_with_retry_opens_a_fresh_connection_each_attempt():
    """A connection whose transaction was aborted cannot be reused."""
    opened = []

    def open_conn():
        c = _FakeConn(raise_on_commit=psycopg2.errors.SerializationFailure()
                      if not opened else None)
        opened.append(c)
        return c

    with_retry(open_conn, lambda _c: None, sleep=lambda _: None)
    assert len(opened) == 2
    assert all(c.closed for c in opened), "every attempt must close its connection"


def test_with_retry_gives_up_and_reraises():
    """Retrying forever would hide a genuine, persistent contention problem."""
    def open_conn():
        return _FakeConn(raise_on_commit=psycopg2.errors.SerializationFailure())

    with pytest.raises(psycopg2.errors.SerializationFailure):
        with_retry(open_conn, lambda _c: None, attempts=3, sleep=lambda _: None)


def test_with_retry_does_not_retry_an_unrelated_error():
    """Only 40001/deadlock is replayable. A bad statement must fail loudly."""
    def work(_cur):
        raise ValueError("bug in the row builder")

    conn = _FakeConn()
    with pytest.raises(ValueError):
        with_retry(lambda: conn, work, sleep=lambda _: None)
    assert conn.closed
    assert not conn.committed


def test_with_retry_commits_once_on_the_happy_path():
    conn = _FakeConn()
    assert with_retry(lambda: conn, lambda _c: 42, sleep=lambda _: None) == 42
    assert conn.committed and conn.closed


# ── push ──────────────────────────────────────────────────────────────────

def _stage_sections_only(tmp_path, n_sections=1):
    stage = str(tmp_path / "stage.db")
    client = FakeClient({"202630": [section(str(i)) for i in range(n_sections)]}, {},
                        terms=TERMS)
    run(client, lambda: sqlite3.connect(stage), "backfill", since_term="202630",
        instructors_from="202710")
    return stage


def test_push_of_a_sections_only_stage_keeps_prods_imported_instructors(db, tmp_path):
    """The reviewer's repro: prod held import rows for the term, the stage had
    none, and the push deleted them and relabelled the term 'none'."""
    conn = db()
    c = conn.cursor()
    apply_ddl(c)
    write_term(c, "202630", SPRING, None,
               scrape([sec("0")], [ins("202630", "0"), ins("202630", "0", "pat hurley")]))
    c.execute("UPDATE banner_section_instructors SET source = 'import'")
    c.execute("UPDATE banner_terms SET instructors_source = 'import'")
    conn.commit()

    assert push(_stage_sections_only(tmp_path), db) == 0
    cur = db().cursor()
    assert sorted(cur.execute("SELECT term_code, crn, source FROM banner_section_instructors")) == [
        ("202630", "0", "import"), ("202630", "0", "import")]
    assert cur.execute("SELECT instructors_source, attributed_sections, instructor_count "
                       "FROM banner_terms").fetchone() == ("import", 1, 2)


def test_push_refuses_a_term_far_smaller_than_prods(db, tmp_path):
    conn = db()
    c = conn.cursor()
    apply_ddl(c)
    write_term(c, "202630", SPRING, None, scrape([sec(str(i)) for i in range(10)], []))
    conn.commit()

    assert push(_stage_sections_only(tmp_path, n_sections=5), db) == 1
    assert count(db().cursor(), "banner_sections", "202630") == 10


def test_push_refuses_an_open_snapshot_over_a_closed_term(db, tmp_path):
    stage = str(tmp_path / "stage.db")
    run(FakeClient({"202710": [section("1")]}, {"1": ANNIE}, terms=TERMS),
        lambda: sqlite3.connect(stage), "current")
    conn = db()
    c = conn.cursor()
    apply_ddl(c)
    write_term(c, "202710", {**FALL, "view_only": True}, None,
               scrape([sec("1")], [ins("202710", "1", "pat hurley")]))
    conn.commit()

    assert push(stage, db) == 1
    assert db().cursor().execute(
        "SELECT instructor_key FROM banner_section_instructors").fetchall() == [("pat hurley",)]


def _stage_open_term(tmp_path, scraped_at):
    stage = str(tmp_path / "stage.db")
    run(FakeClient({"202710": [section("1")]}, {"1": ANNIE}, terms=TERMS),
        lambda: sqlite3.connect(stage), "current")
    conn = sqlite3.connect(stage)
    conn.execute("UPDATE banner_terms SET scraped_at = ?", (scraped_at,))
    conn.commit()
    return stage


def test_push_refuses_a_stage_older_than_prods_scrape(db, tmp_path, capsys):
    """An old stage used to overwrite the weekly run's newer scrape of an open
    term, and the push stamped it now(), so it then read as fresh."""
    stage = _stage_open_term(tmp_path, "2026-09-01 08:00:00")
    conn = db()
    c = conn.cursor()
    apply_ddl(c)
    write_term(c, "202710", FALL, None, scrape([sec("1")], [ins("202710", "1", "pat hurley")]))
    c.execute("UPDATE banner_terms SET scraped_at = '2026-09-28 08:00:00'")
    conn.commit()

    assert push(stage, db) == 1
    assert "older than prod's" in capsys.readouterr().err
    cur = db().cursor()
    assert cur.execute("SELECT instructor_key FROM banner_section_instructors").fetchall() == [
        ("pat hurley",)]
    assert cur.execute("SELECT scraped_at FROM banner_terms").fetchone() == (
        "2026-09-28 08:00:00",)


def test_push_keeps_the_stages_own_scraped_at(db, tmp_path):
    stage = _stage_open_term(tmp_path, "2026-09-01 08:00:00")
    assert push(stage, db) == 0
    assert push(stage, db) == 0     # same scrape again is not "older"
    assert db().cursor().execute("SELECT scraped_at FROM banner_terms").fetchone() == (
        "2026-09-01T08:00:00+00:00",)


# ── connect ───────────────────────────────────────────────────────────────

def test_connect_retries_the_dns_flake(monkeypatch):
    attempts = []

    def flaky(dsn, sslmode):
        attempts.append(sslmode)
        if len(attempts) < 3:
            raise psycopg2.OperationalError('could not translate host name "x" to address')
        return "conn"

    monkeypatch.setattr(load_banner_to_crdb.psycopg2, "connect", flaky)
    assert connect("postgres://x", sleep=lambda _: None) == "conn"
    assert attempts == ["require"] * 3


def test_connect_does_not_retry_other_errors(monkeypatch):
    def refused(dsn, sslmode):
        raise psycopg2.OperationalError("password authentication failed")

    monkeypatch.setattr(load_banner_to_crdb.psycopg2, "connect", refused)
    with pytest.raises(psycopg2.OperationalError, match="password"):
        connect("postgres://x", sleep=lambda _: pytest.fail("must not retry"))


# ── main ──────────────────────────────────────────────────────────────────

def test_main_exits_75_on_a_rate_limit_so_the_workflow_skips_finalize(
        monkeypatch, tmp_path, capsys):
    from banner_client import BannerRateLimited

    def rate_limited(*_a, **_k):
        raise BannerRateLimited("429 from term/search")

    monkeypatch.setattr(load_banner_to_crdb, "run", rate_limited)
    assert load_banner_to_crdb.main(["--local-db", str(tmp_path / "x.db")]) == 75
    assert "RATE LIMITED" in capsys.readouterr().err
