"""The admin app's Purge account button must purge exactly what clear_ask_strikes.py
--purge-account does (both call purge_account_data). Fake connection, no live DB."""

import importlib
import os

import pytest

os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
os.environ.setdefault("JWT_SECRET", "test-secret")

import rating_identity
from tests.test_purge_bookmarks import COUNTS, SECRET, FakeConn, FakeCursor


class AdminConn(FakeConn):
    def __init__(self, cur):
        super().__init__()
        self.cur = cur

    def cursor(self, *a, **k):
        return self

    def __enter__(self):
        return self.cur

    def __exit__(self, *exc):
        return False


@pytest.fixture
def admin(monkeypatch):
    import psycopg2
    cur = FakeCursor(COUNTS, opted_out=True)
    conn = AdminConn(cur)
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: conn)
    module = importlib.import_module("rag.ask_admin")
    monkeypatch.setattr(module, "conn", conn)
    monkeypatch.setenv("RATING_SECRET", SECRET)
    return module.app.test_client(), cur, conn


def deletes(cur):
    return {s.split()[2]: p for s, p in cur.executed if s.lower().startswith("delete")}


def test_dry_run_counts_everything_and_deletes_nothing(admin):
    client, cur, conn = admin
    got = client.post("/api/users/user-1/purge", json={"dry_run": True}).get_json()
    assert got == {"deleted": 3, "bookmarks_deleted": 2, "ratings_deleted": 4, "profiles_deleted": 1,
                   "page_views_deleted": 9, "opt_out_kept": True}
    assert deletes(cur) == {} and conn.commits == 0


def test_purge_deletes_what_the_script_does(admin):
    client, cur, conn = admin
    got = client.post("/api/users/user-1/purge", json={"dry_run": False}).get_json()
    assert got["deleted"] == 3 and got["bookmarks_deleted"] == 2   # keys the page already reads
    assert got["ratings_deleted"] == 4 and got["page_views_deleted"] == 9 and got["opt_out_kept"] is True
    assert deletes(cur) == {
        "ask_log": ("user-1",), "bookmarks": ("user-1",),
        "survey_ratings": (rating_identity.keyed_hash(SECRET, "account", "user-1"),),
        "student_profiles": ("user-1",),
        "page_views": (rating_identity.keyed_hash(SECRET, "viewer", "user-1"),)}
    assert any(s.startswith("INSERT INTO student_profiles") for s, _ in cur.executed)   # opted-out row put back
    assert conn.commits == 1


@pytest.mark.parametrize("dry_run", [True, False])
def test_purge_without_a_rating_secret_refuses_before_touching_anything(admin, monkeypatch, dry_run):
    client, cur, conn = admin
    monkeypatch.delenv("RATING_SECRET")
    resp = client.post("/api/users/user-1/purge", json={"dry_run": dry_run})
    assert resp.status_code == 500 and "RATING_SECRET" in resp.get_json()["error"]
    assert cur.executed == [] and conn.commits == 0
