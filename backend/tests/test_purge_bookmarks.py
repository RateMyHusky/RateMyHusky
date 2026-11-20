"""Data-erasure coverage: purge_account in clear_ask_strikes.py must delete a
user's bookmarks and signed-in ratings along with their ask_log rows, and its
dry-run must report all three without deleting anything. Uses fake conn/cur — no live DB."""

import os

import pytest

# clear_ask_strikes runs load_dotenv(backend/.env) at import, and this import
# happens at pytest collection time — pin the env vars the other test files'
# fixtures rely on FIRST so the real .env can't override them (python-dotenv
# never overwrites already-set vars).
os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
os.environ.setdefault("JWT_SECRET", "test-secret")

from rag.clear_ask_strikes import purge_account
import rating_identity
from pipeline.read_models import DATA_VERSION_SQL

SECRET = "rating-secret-0123456789abcdefghijklmnop"  # gitleaks:allow
ACCOUNT_HASH = rating_identity.keyed_hash(SECRET, "account", "user-1")


class FakeCursor:
    """Answers count(*) selects per table and records every execute."""

    def __init__(self, counts):
        self.counts = counts  # {"ask_log": n, "bookmarks": n, "survey_ratings": n}
        self.executed = []
        self.rowcount = 0
        self._next_fetch = None

    def _table(self, sql):
        return next(t for t in ("bookmarks", "survey_ratings", "ask_log") if t in sql.lower())

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
    cur = FakeCursor({"ask_log": 3, "bookmarks": 2, "survey_ratings": 4})
    conn = FakeConn()
    purge_account(conn, cur, "user-1", dry_run=True, rating_secret=SECRET)
    deletes = [s for s, _ in cur.executed if s.lower().strip().startswith("delete")]
    assert deletes == []
    assert conn.commits == 0
    out = capsys.readouterr().out
    assert "2 bookmark" in out and "4 rating" in out


def test_purge_deletes_ask_log_bookmarks_and_ratings_then_commits():
    cur = FakeCursor({"ask_log": 3, "bookmarks": 2, "survey_ratings": 4})
    conn = FakeConn()
    purge_account(conn, cur, "user-1", dry_run=False, rating_secret=SECRET)
    deletes = {next(t for t in ("bookmarks", "survey_ratings", "ask_log") if t in s.lower()): p
               for s, p in cur.executed if s.lower().strip().startswith("delete")}
    assert deletes == {"ask_log": ("user-1",), "bookmarks": ("user-1",), "survey_ratings": (ACCOUNT_HASH,)}
    assert conn.commits >= 1


def test_purge_without_rating_secret_deletes_nothing():
    cur = FakeCursor({"ask_log": 3, "bookmarks": 2, "survey_ratings": 4})
    conn = FakeConn()
    with pytest.raises(SystemExit):
        purge_account(conn, cur, "user-1", dry_run=False, rating_secret=None)
    assert cur.executed == [] and conn.commits == 0


def test_purge_bumps_data_version_so_cached_professor_pages_drop_the_ratings():
    cur = FakeCursor({"ask_log": 3, "bookmarks": 2, "survey_ratings": 4})
    conn = FakeConn()
    purge_account(conn, cur, "user-1", dry_run=False, rating_secret=SECRET)
    sqls = [s for s, _ in cur.executed]
    rating_delete = next(i for i, s in enumerate(sqls) if "delete from survey_ratings" in s.lower())
    assert DATA_VERSION_SQL in sqls[rating_delete:]
