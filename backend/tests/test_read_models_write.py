"""read_models.write replaces the read models in ONE transaction, with no DDL.

Readers see the last committed snapshot, so DELETE + INSERT is invisible to the
site until COMMIT, and then all three tables and data_version change together.
No CREATE/ALTER/DROP may run: the tables keep db/postgres/'s schema exactly.
"""

import pytest

from pipeline import db, read_models


class FakeCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.log.append(("execute", " ".join(sql.split())))


class FakeConn:
    def __init__(self):
        self.log = []

    def cursor(self):
        return FakeCursor(self.log)

    def commit(self):
        self.log.append(("commit",))

    def rollback(self):
        self.log.append(("rollback",))


ROW = {c: None for c in read_models.CATALOG_COLUMNS}
COURSE = {c: None for c in read_models.COURSE_COLUMNS}
SUMMARY = {c: None for c in read_models.SUMMARY_COLUMNS}
COUNTS = {"professors": 1, "courses": 1, "comments": 0, "departments": 0}


@pytest.fixture
def inserts(monkeypatch):
    def fake_execute_values(cur, sql, rows):
        cur.log.append(("insert", sql.split(" (")[0], len(rows)))
    monkeypatch.setattr(db, "execute_values", fake_execute_values)


def test_each_table_is_deleted_then_reinserted(inserts):
    conn = FakeConn()
    read_models.write(conn, [ROW], [COURSE], [SUMMARY], COUNTS)
    for table in read_models.READ_MODELS:
        delete = conn.log.index(("execute", f"DELETE FROM {table}"))
        insert = conn.log.index(("insert", f"INSERT INTO {table}", 1))
        assert delete < insert


def test_stats_and_data_version_use_on_conflict(inserts):
    conn = FakeConn()
    read_models.write(conn, [ROW], [COURSE], [SUMMARY], COUNTS)
    stats = [e[1] for e in conn.log if e[0] == "execute" and "stats_cache" in e[1]]
    assert len(stats) == 2
    assert all("ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value" in s for s in stats)
    assert any("'data_version', COALESCE(max(value), 0) + 1" in s for s in stats)


def test_no_ddl_and_exactly_one_commit_at_the_end(inserts):
    conn = FakeConn()
    read_models.write(conn, [ROW], [COURSE], [SUMMARY], COUNTS)
    statements = [e[1] for e in conn.log if e[0] == "execute"]
    assert not [s for s in statements if s.split()[0] in ("CREATE", "ALTER", "DROP", "TRUNCATE")]
    assert conn.log.count(("commit",)) == 1
    assert conn.log[-1] == ("commit",)


def test_a_failed_insert_rolls_back_and_never_commits(monkeypatch):
    def failing_execute_values(cur, sql, rows):
        if "course_catalog" in sql:
            raise RuntimeError("boom")
    monkeypatch.setattr(db, "execute_values", failing_execute_values)
    conn = FakeConn()
    with pytest.raises(RuntimeError, match="boom"):
        read_models.write(conn, [ROW], [COURSE], [SUMMARY], COUNTS)
    assert ("rollback",) in conn.log
    assert ("commit",) not in conn.log
