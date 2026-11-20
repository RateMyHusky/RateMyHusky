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

from rag.clear_ask_strikes import opt_out, purge_account, purge_account_data
import rating_identity
from pipeline.read_models import DATA_VERSION_SQL

SECRET = "rating-secret-0123456789abcdefghijklmnop"  # gitleaks:allow
ACCOUNT_HASH = rating_identity.keyed_hash(SECRET, "account", "user-1")
VIEWER_HASH = rating_identity.keyed_hash(SECRET, "viewer", "user-1")


COUNTS = {"ask_log": 3, "bookmarks": 2, "survey_ratings": 4, "student_profiles": 1, "page_views": 9}


class FakeCursor:
    """Answers count(*) selects per table and records every execute."""

    def __init__(self, counts, opted_out=False):
        self.counts = counts  # {"ask_log": n, "bookmarks": n, "survey_ratings": n, ...}
        self.opted_out = opted_out
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
            n = self.counts[self._table(sql)]
            self._next_fetch = (int(n and self.opted_out) if "tracking_opt_out" in low else n,)
        elif low.startswith("delete"):
            self.rowcount = self.counts[self._table(sql)]

    def fetchone(self):
        return self._next_fetch

    def fetchall(self):   # DELETE FROM student_profiles ... RETURNING tracking_opt_out
        return [(self.opted_out,)] * self.counts["student_profiles"]


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
    assert "opt-out still holds" not in out


def test_purge_deletes_ask_log_bookmarks_and_ratings_then_commits():
    cur = FakeCursor(COUNTS)
    conn = FakeConn()
    purge_account(conn, cur, "user-1", dry_run=False, rating_secret=SECRET)
    deletes = {next(t for t in ("bookmarks", "survey_ratings", "ask_log", "student_profiles", "page_views")
                    if t in s.lower()): p
               for s, p in cur.executed if s.lower().strip().startswith("delete")}
    assert deletes == {"ask_log": ("user-1",), "bookmarks": ("user-1",), "survey_ratings": (ACCOUNT_HASH,),
                       "student_profiles": ("user-1",), "page_views": (VIEWER_HASH,)}
    assert VIEWER_HASH != ACCOUNT_HASH
    assert conn.commits >= 1


def inserts(cur):
    return [(s, p) for s, p in cur.executed if s.lower().startswith("insert into student_profiles")]


def test_purge_of_an_opted_out_account_puts_the_opted_out_row_back(capsys):
    cur = FakeCursor(COUNTS, opted_out=True)
    conn = FakeConn()
    purge_account(conn, cur, "user-1", dry_run=False, rating_secret=SECRET)
    sqls = [s.lower() for s, _ in cur.executed]
    ins = inserts(cur)
    assert len(ins) == 1 and ins[0][1] == ("user-1",)
    assert "insert into student_profiles" in ins[0][0].lower() and "tracking_opt_out" in ins[0][0]
    assert sqls.index(next(s for s in sqls if s.startswith("delete from student_profiles"))) <         sqls.index(ins[0][0].lower())
    assert "opt-out still holds" in capsys.readouterr().out


def test_purge_of_an_account_that_never_opted_out_leaves_no_row():
    cur = FakeCursor(COUNTS)
    purge_account(FakeConn(), cur, "user-1", dry_run=False, rating_secret=SECRET)
    assert inserts(cur) == []


def test_purge_dry_run_says_the_opt_out_is_kept(capsys):
    cur = FakeCursor(COUNTS, opted_out=True)
    purge_account(FakeConn(), cur, "user-1", dry_run=True, rating_secret=SECRET)
    assert inserts(cur) == []
    assert "opt-out still holds" in capsys.readouterr().out


def test_purge_account_data_returns_the_counts():
    cur = FakeCursor(COUNTS, opted_out=True)
    want = {"ask_log": 3, "bookmarks": 2, "ratings": 4, "profiles": 1, "page_views": 9, "opt_out_kept": True}
    assert purge_account_data(FakeConn(), cur, "user-1", False, SECRET) == want
    assert purge_account_data(FakeConn(), FakeCursor(COUNTS, opted_out=True), "user-1", True, SECRET) == want


def test_purge_account_data_without_a_secret_raises_before_touching_anything():
    cur = FakeCursor(COUNTS)
    with pytest.raises(ValueError):
        purge_account_data(FakeConn(), cur, "user-1", False, None)
    assert cur.executed == []


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


def test_opt_out_sets_the_flag_and_deletes_views(capsys):
    cur = FakeCursor({"page_views": 7, "student_profiles": 1}); conn = FakeConn()
    opt_out(conn, cur, "user-1", dry_run=False, rating_secret=SECRET)
    assert "existing profile" in capsys.readouterr().out
    sqls = [s.lower() for s, _ in cur.executed]
    delete = next(i for i, s in enumerate(sqls) if s.startswith("delete from page_views"))
    upsert = next(i for i, s in enumerate(sqls) if "tracking_opt_out" in s and "on conflict" in s)
    assert upsert < delete   # flag first, so a view in flight can't land after the delete
    assert [p for s, p in cur.executed if s.lower().startswith("delete from page_views")] == [(VIEWER_HASH,)]
    assert not any("survey_ratings" in s for s in sqls)   # existing ratings keep their year
    assert conn.commits == 1


def test_opt_out_dry_run_changes_nothing(capsys):
    cur = FakeCursor({"page_views": 7, "student_profiles": 1}); conn = FakeConn()
    opt_out(conn, cur, "user-1", dry_run=True, rating_secret=SECRET)
    sqls = [s.lower().strip() for s, _ in cur.executed]
    assert not any(s.startswith(("delete", "insert", "update")) for s in sqls)
    assert conn.commits == 0
    out = capsys.readouterr().out
    assert "7 page view" in out and "existing profile" in out


def test_opt_out_dry_run_says_when_there_is_no_profile(capsys):
    cur = FakeCursor({"page_views": 0, "student_profiles": 0}); conn = FakeConn()
    opt_out(conn, cur, "typo-sub", dry_run=True, rating_secret=SECRET)
    assert "no profile: will create an opted-out row" in capsys.readouterr().out
    assert conn.commits == 0


def test_opt_out_without_a_profile_creates_an_opted_out_row(capsys):
    cur = FakeCursor({"page_views": 0, "student_profiles": 0}); conn = FakeConn()
    opt_out(conn, cur, "user-1", dry_run=False, rating_secret=SECRET)
    assert "no profile: created an opted-out row" in capsys.readouterr().out
    upserts = [(s, p) for s, p in cur.executed if "on conflict" in s.lower()]
    assert len(upserts) == 1
    assert upserts[0][1] == ("user-1",)
    assert "insert into student_profiles" in upserts[0][0].lower()
    assert conn.commits == 1


@pytest.mark.parametrize("dry_run", [False, True])
def test_opt_out_without_rating_secret_touches_nothing(dry_run):
    cur = FakeCursor({"page_views": 7, "student_profiles": 1}); conn = FakeConn()
    with pytest.raises(SystemExit):
        opt_out(conn, cur, "user-1", dry_run=dry_run, rating_secret=None)
    assert cur.executed == [] and conn.commits == 0
