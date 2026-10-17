"""Data-erasure coverage: purge_account in clear_ask_strikes.py must delete a
user's bookmarks along with their ask_log rows, and its dry-run must report
both without deleting anything. Uses fake conn/cur — no live DB."""

import os

# clear_ask_strikes runs load_dotenv(backend/.env) at import, and this import
# happens at pytest collection time — pin the env vars the other test files'
# fixtures rely on FIRST so the real .env can't override them (python-dotenv
# never overwrites already-set vars).
os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
os.environ.setdefault("JWT_SECRET", "test-secret")

from rag.clear_ask_strikes import purge_account


class FakeCursor:
    """Answers count(*) selects per table and records every execute."""

    def __init__(self, counts):
        self.counts = counts  # {"ask_log": n, "bookmarks": n}
        self.executed = []
        self.rowcount = 0
        self._next_fetch = None

    def _table(self, sql):
        return "bookmarks" if "bookmarks" in sql.lower() else "ask_log"

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        low = sql.lower().strip()
        if low.startswith("select count(*)"):
            self._next_fetch = (self.counts[self._table(sql)],)
        elif low.startswith("delete"):
            self.rowcount = self.counts[self._table(sql)]

    def fetchone(self):
        return self._next_fetch


class FakeConn:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def test_purge_dry_run_reports_bookmark_count_and_deletes_nothing(capsys):
    cur = FakeCursor({"ask_log": 3, "bookmarks": 2})
    conn = FakeConn()
    purge_account(conn, cur, "user-1", dry_run=True)
    deletes = [s for s, _ in cur.executed if s.lower().strip().startswith("delete")]
    assert deletes == []
    assert conn.commits == 0
    out = capsys.readouterr().out
    assert "2 bookmark" in out


def test_purge_deletes_ask_log_and_bookmarks_then_commits():
    cur = FakeCursor({"ask_log": 3, "bookmarks": 2})
    conn = FakeConn()
    purge_account(conn, cur, "user-1", dry_run=False)
    deletes = [s for s, _ in cur.executed if s.lower().strip().startswith("delete")]
    assert any("ask_log" in d for d in deletes)
    assert any("bookmarks" in d for d in deletes)
    assert all(params == ("user-1",) for _, params in cur.executed)
    assert conn.commits >= 1
