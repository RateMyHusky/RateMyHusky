"""Evidence prune guard: the pure checks, planning by full row key, and the single-commit
prune over a fake connection. No DB."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from load_evidence import (  # noqa: E402
    CHANGE_CEILING, DRAIN_CEILING, PRUNE_CEILING, _row, check_plans, check_prune,
    plan_source, prune_evidence,
)


# ── check_prune ──

def test_prune_refuses_when_build_returned_nothing():
    with pytest.raises(SystemExit, match="reddit"):
        check_prune("reddit", n_db=8789, n_fresh=0, n_stale=8789, force=True)


def test_prune_refuses_over_ceiling_without_force():
    with pytest.raises(SystemExit, match="rmp"):
        check_prune("rmp", n_db=40000, n_fresh=30000, n_stale=10000, force=False)


def test_prune_allows_over_ceiling_with_force():
    check_prune("rmp", n_db=40000, n_fresh=30000, n_stale=10000, force=True, peak=41000)


def test_prune_allows_normal_week():
    check_prune("rmp", n_db=41392, n_fresh=44900, n_stale=14, force=False, n_changed=30, peak=41392)


def test_stale_ceiling_only_applies_to_a_prune():
    check_prune("rmp", n_db=40000, n_fresh=40000, n_stale=10000, force=False, prune=False)


def test_rewriting_too_many_bodies_is_refused():
    # Mangled text would otherwise be upserted and re-embedded the same day.
    with pytest.raises(SystemExit, match="changes the text of 2500"):
        check_prune("rmp", n_db=40000, n_fresh=40000, n_stale=0, force=False, n_changed=2500)
    check_prune("rmp", n_db=40000, n_fresh=40000, n_stale=0, force=True, n_changed=2500)


def test_slow_drain_is_caught_against_the_peak():
    # 4% stale this week passes the weekly ceiling, but the corpus is now 12% under its peak.
    with pytest.raises(SystemExit, match="under the source's peak"):
        check_prune("rmp", n_db=36700, n_fresh=35200, n_stale=1500, force=False, peak=40000)
    check_prune("rmp", n_db=36700, n_fresh=35200, n_stale=1500, force=True, peak=40000)


def test_no_peak_yet_means_no_drain_check():
    check_prune("rmp", n_db=100, n_fresh=50, n_stale=0, force=False, peak=None, prune=False)


def test_ceiling_values():
    assert (PRUNE_CEILING, CHANGE_CEILING, DRAIN_CEILING) == (0.05, 0.05, 0.10)


# ── plan_source / prune_evidence over a fake connection ──

class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.statements.append((sql, params))
        if sql.startswith("DELETE FROM evidence WHERE"):
            self.rowcount = len(params[0])

    def fetchall(self):
        return self.conn.db_rows

    def fetchone(self):
        return (self.conn.peak,) if self.conn.peak is not None else None


class _FakeConn:
    """Holds a source's evidence rows (id, source_ref, slug, course_code, body_sha) and its
    peak; records every statement and commit."""
    def __init__(self, db_rows, peak=None):
        self.db_rows = db_rows
        self.peak = peak
        self.statements = []
        self.commits = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def writes(self):
        return [s for s in self.statements if not s[0].startswith("SELECT")]


BODY = "a long enough review body to count as meaningful text"


def rmp(ref, slug="guha", code="CS3500", body=BODY):
    return _row("rmp", ref, slug, code, body)


def db_row(row_id, r, sha=None):
    return (row_id, r["source_ref"], r["professor_slug"], r["course_code"], sha or r["body_sha"])


def test_plan_finds_rows_whose_professor_or_course_changed():
    same, recoded, moved = rmp("1"), rmp("2", code="CS3650"), rmp("3", slug="lee")
    db = [db_row(1, same),
          db_row(2, rmp("2", code="CS3600")),   # course code corrected since: old row is stale
          db_row(3, rmp("3", slug="guha")),     # re-matched to another professor: old row is stale
          db_row(4, rmp("4"))]                  # review gone
    plan = plan_source(_FakeConn(db), "rmp", [same, recoded, moved])
    assert plan["stale_ids"] == [2, 3, 4]
    assert (plan["n_db"], plan["n_fresh"], plan["n_changed"]) == (4, 3, 0)


def test_plan_counts_rows_whose_text_changes():
    r = rmp("1")
    plan = plan_source(_FakeConn([db_row(1, r, sha="old")], peak=1), "rmp", [r])
    assert plan["n_changed"] == 1 and plan["stale_ids"] == [] and plan["peak"] == 1


def test_a_failing_source_stops_both_before_any_write():
    good = {"source": "reddit", "n_db": 100, "n_fresh": 100, "stale_ids": [], "n_changed": 0, "peak": 100}
    bad = {"source": "rmp", "n_db": 100, "n_fresh": 80, "stale_ids": list(range(20)), "n_changed": 0, "peak": 100}
    with pytest.raises(SystemExit, match="rmp"):
        check_plans([good, bad], force=False, prune=True)


def test_prune_deletes_by_id_for_every_source_in_one_commit():
    conn = _FakeConn([])
    plans = [{"source": "reddit", "n_fresh": 9000, "stale_ids": [5], "peak": 9100},
             {"source": "rmp", "n_fresh": 41500, "stale_ids": [7, 8, 9], "peak": 41000}]
    deleted = prune_evidence(conn, plans, batch=2)
    assert deleted == {"reddit": 1, "rmp": 3}
    assert conn.commits == 1
    deletes = [(sql.split(" WHERE")[0], params[0]) for sql, params in conn.writes() if sql.startswith("DELETE")]
    assert deletes == [("DELETE FROM evidence_embeddings", [5]), ("DELETE FROM evidence", [5]),
                       ("DELETE FROM evidence_embeddings", [7, 8]), ("DELETE FROM evidence", [7, 8]),
                       ("DELETE FROM evidence_embeddings", [9]), ("DELETE FROM evidence", [9])]
    peaks = [params for sql, params in conn.writes() if "stats_cache" in sql]
    # The peak only rises on a normal run.
    assert peaks == [("evidence_peak:reddit", 9100), ("evidence_peak:rmp", 41500)]


def test_forced_prune_lowers_the_peak():
    conn = _FakeConn([])
    prune_evidence(conn, [{"source": "rmp", "n_fresh": 30000, "stale_ids": [], "peak": 41000}], force=True)
    assert [p for s, p in conn.writes() if "stats_cache" in s] == [("evidence_peak:rmp", 30000)]
