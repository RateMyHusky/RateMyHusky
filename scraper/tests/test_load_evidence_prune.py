"""Prune safety ceiling: the pure check, and prune_evidence over a fake connection. No DB."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from load_evidence import check_prune, PRUNE_CEILING  # noqa: E402


def test_prune_refuses_when_build_returned_nothing():
    with pytest.raises(SystemExit, match="reddit"):
        check_prune("reddit", n_db=8789, n_fresh=0, n_stale=8789, force=True)


def test_prune_refuses_over_ceiling_without_force():
    with pytest.raises(SystemExit, match="rmp"):
        check_prune("rmp", n_db=40000, n_fresh=30000, n_stale=10000, force=False)


def test_prune_allows_over_ceiling_with_force():
    check_prune("rmp", n_db=40000, n_fresh=30000, n_stale=10000, force=True)


def test_prune_allows_normal_week():
    check_prune("rmp", n_db=41392, n_fresh=44900, n_stale=14, force=False)


def test_ceiling_value():
    assert PRUNE_CEILING == 0.05


class _FakeCursor:
    rowcount = 0

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.statements.append(sql)

    def fetchall(self):
        return [(ref,) for ref in self.conn.db_refs]


class _FakeConn:
    """Holds the source's refs; records every statement and commit."""
    def __init__(self, db_refs):
        self.db_refs = db_refs
        self.statements = []
        self.commits = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def test_prune_evidence_over_ceiling_deletes_nothing():
    from load_evidence import prune_evidence
    conn = _FakeConn([f"r{i}" for i in range(100)])
    fresh = [f"r{i}" for i in range(90)]          # 10 of 100 stale: over the 5% ceiling
    with pytest.raises(SystemExit, match="rmp"):
        prune_evidence(conn, "rmp", fresh, force=False)
    assert not any("DELETE" in s.upper() for s in conn.statements)
    assert conn.commits == 0


def test_prune_evidence_with_force_does_delete():
    # Same fake, force on: shows the fake does see DELETEs, so the test above means something.
    from load_evidence import prune_evidence
    conn = _FakeConn([f"r{i}" for i in range(100)])
    prune_evidence(conn, "rmp", [f"r{i}" for i in range(90)], force=True)
    assert sum("DELETE" in s.upper() for s in conn.statements) == 2 and conn.commits == 1
