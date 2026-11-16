"""Deletion coverage for clear_ask_strikes.py and the shared helpers in chat_abuse.py.

A data deletion removes an account's questions and bookmarks but keeps the strikes that
still count (text removed), so an Ask ban survives it. An account deletion removes
everything, the ban included. Uses fake conn/cur — no live DB; tests/pg/test_deletion_pg.py
runs the same SQL against PostgreSQL."""

import os

# clear_ask_strikes runs load_dotenv(backend/.env) at import, and this import
# happens at pytest collection time — pin the env vars the other test files'
# fixtures rely on FIRST so the real .env can't override them (python-dotenv
# never overwrites already-set vars).
os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
os.environ.setdefault("JWT_SECRET", "test-secret")

from rag.chat_abuse import DELETED_TEXT, STRIKE_STATUSES, STRIKE_WINDOW_DAYS
from rag.clear_ask_strikes import delete_for


class FakeCursor:
    """Answers the count selects and records every execute."""

    def __init__(self, ask_rows=5, live_strikes=2, bookmarks=3):
        self.counts = {"ask_rows": ask_rows, "live_strikes": live_strikes, "bookmarks": bookmarks}
        self.executed = []
        self.rowcount = 0
        self._next_fetch = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        low = sql.lower().strip()
        if low.startswith("select") and "bookmarks" in low:
            self._next_fetch = (self.counts["bookmarks"],)
        elif low.startswith("select"):
            self._next_fetch = (self.counts["ask_rows"], self.counts["live_strikes"])
        elif low.startswith("update"):
            self.rowcount = self.counts["live_strikes"]
        elif "bookmarks" in low:
            self.rowcount = self.counts["bookmarks"]
        elif "is not true" in low:
            self.rowcount = self.counts["ask_rows"] - self.counts["live_strikes"]
        else:
            self.rowcount = self.counts["ask_rows"]

    def fetchone(self):
        return self._next_fetch

    def writes(self):
        return [(s, p) for s, p in self.executed if not s.lower().strip().startswith("select")]


class FakeConn:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def test_dry_runs_write_nothing_and_report_what_would_go(capsys):
    for keep, expected in ((True, "would delete 3 ask_log row(s) and 3 bookmark row(s)"),
                           (False, "would delete 5 ask_log row(s) and 3 bookmark row(s)")):
        cur, conn = FakeCursor(), FakeConn()
        delete_for(conn, cur, "user-1", keep_standing=keep, dry_run=True)
        assert cur.writes() == [] and conn.commits == 0
        out = capsys.readouterr().out
        assert expected in out
        assert ("keeping 2 live strike(s)" in out) is keep


def test_data_deletion_keeps_live_strikes_without_their_text(capsys):
    cur, conn = FakeCursor(), FakeConn()
    delete_for(conn, cur, "user-1", keep_standing=True, dry_run=False)
    (upd, upd_params), (dele, del_params), (bm, bm_params) = cur.writes()
    # The live strikes are scrubbed, not deleted, so the ban ladder still counts them...
    assert upd.startswith("UPDATE ask_log SET query = %s, answer_text = NULL")
    assert upd_params == (DELETED_TEXT, "user-1", list(STRIKE_STATUSES), STRIKE_WINDOW_DAYS)
    # ...and every other row for the account goes, NULL created_at included.
    assert dele.startswith("DELETE FROM ask_log WHERE session_token = %s AND (")
    assert dele.endswith(") IS NOT TRUE")
    assert del_params == ("user-1", list(STRIKE_STATUSES), STRIKE_WINDOW_DAYS)
    assert bm == "DELETE FROM bookmarks WHERE user_sub = %s" and bm_params == ("user-1",)
    assert conn.commits == 1
    assert "Kept 2 live strike(s)" in capsys.readouterr().out


def test_account_deletion_removes_every_row_ban_included(capsys):
    cur, conn = FakeCursor(), FakeConn()
    delete_for(conn, cur, "user-1", keep_standing=False, dry_run=False)
    assert cur.writes() == [
        ("DELETE FROM ask_log WHERE session_token = %s", ("user-1",)),
        ("DELETE FROM bookmarks WHERE user_sub = %s", ("user-1",)),
    ]
    assert conn.commits == 1
    out = capsys.readouterr().out
    assert "Deleted 5 ask_log row(s) and 3 bookmark row(s)" in out and "any ban included" in out
