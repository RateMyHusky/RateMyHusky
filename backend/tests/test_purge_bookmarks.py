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

from rag.clear_ask_strikes import opt_out, purge_account
import rating_identity
from pipeline.read_models import DATA_VERSION_SQL

SECRET = "rating-secret-0123456789abcdefghijklmnop"  # gitleaks:allow
ACCOUNT_HASH = rating_identity.keyed_hash(SECRET, "account", "user-1")


COUNTS = {"ask_log": 3, "bookmarks": 2, "survey_ratings": 4, "student_profiles": 1, "page_views": 9}


class FakeCursor:
    """Answers count(*) selects per table and records every execute."""

    def __init__(self, counts):
        self.counts = counts  # {"ask_log": n, "bookmarks": n, "survey_ratings": n, ...}
        self.executed = []
        self.rowcount = 0
        self._next_fetch = None

    def _table(self, sql):
        return next(t for t in ("bookmarks", "survey_ratings", "ask_log", "student_profiles", "page_views")
                    if t in sql.lower())

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
    cur = FakeCursor(COUNTS)
    conn = FakeConn()
    purge_account(conn, cur, "user-1", dry_run=True, rating_secret=SECRET)
    deletes = [s for s, _ in cur.executed if s.lower().strip().startswith("delete")]
    assert deletes == []
    assert conn.commits == 0
    out = capsys.readouterr().out
    assert "2 bookmark" in out and "4 rating" in out
    assert "1 student profile" in out and "9 page view" in out


def test_purge_deletes_ask_log_bookmarks_and_ratings_then_commits():
    cur = FakeCursor(COUNTS)
    conn = FakeConn()
    purge_account(conn, cur, "user-1", dry_run=False, rating_secret=SECRET)
    deletes = {next(t for t in ("bookmarks", "survey_ratings", "ask_log", "student_profiles", "page_views")
                    if t in s.lower()): p
               for s, p in cur.executed if s.lower().strip().startswith("delete")}
    assert deletes == {"ask_log": ("user-1",), "bookmarks": ("user-1",), "survey_ratings": (ACCOUNT_HASH,),
                       "student_profiles": ("user-1",), "page_views": ("user-1",)}
    assert conn.commits >= 1


def test_purge_without_rating_secret_deletes_nothing():
    cur = FakeCursor(COUNTS)
    conn = FakeConn()
    with pytest.raises(SystemExit):
        purge_account(conn, cur, "user-1", dry_run=False, rating_secret=None)
    assert cur.executed == [] and conn.commits == 0


def test_purge_bumps_data_version_so_cached_professor_pages_drop_the_ratings():
    cur = FakeCursor(COUNTS)
    conn = FakeConn()
    purge_account(conn, cur, "user-1", dry_run=False, rating_secret=SECRET)
    sqls = [s for s, _ in cur.executed]
    rating_delete = next(i for i, s in enumerate(sqls) if "delete from survey_ratings" in s.lower())
    assert DATA_VERSION_SQL in sqls[rating_delete:]


def test_opt_out_sets_the_flag_and_deletes_views():
    cur = FakeCursor({"page_views": 7, "student_profiles": 1}); conn = FakeConn()
    opt_out(conn, cur, "user-1", dry_run=False)
    sqls = [s.lower() for s, _ in cur.executed]
    assert any(s.startswith("delete from page_views") for s in sqls)
    assert any("tracking_opt_out" in s and "on conflict" in s for s in sqls)
    assert not any("survey_ratings" in s for s in sqls)   # existing ratings keep their year
    assert conn.commits == 1


def test_opt_out_dry_run_changes_nothing(capsys):
    cur = FakeCursor({"page_views": 7, "student_profiles": 1}); conn = FakeConn()
    opt_out(conn, cur, "user-1", dry_run=True)
    sqls = [s.lower().strip() for s, _ in cur.executed]
    assert not any(s.startswith(("delete", "insert", "update")) for s in sqls)
    assert conn.commits == 0
    assert "7 page view" in capsys.readouterr().out


def test_opt_out_without_a_profile_creates_an_opted_out_row():
    cur = FakeCursor({"page_views": 0, "student_profiles": 0}); conn = FakeConn()
    opt_out(conn, cur, "user-1", dry_run=False)
    upserts = [(s, p) for s, p in cur.executed if "on conflict" in s.lower()]
    assert len(upserts) == 1
    assert upserts[0][1] == ("user-1",)
    assert "insert into student_profiles" in upserts[0][0].lower()
    assert conn.commits == 1
