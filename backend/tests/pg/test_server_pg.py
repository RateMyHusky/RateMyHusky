"""Flask endpoints, bookmarks and usage alerts through the real pool."""

import psycopg2.extras
import pytest

import bookmarks
import review_ratings
import usage_alert
from pipeline import read_models
from tests.pg.pgutil import truncate
from tests.pg.seed import CATALOG, COUNTS, COURSES, SUMMARIES


@pytest.fixture
def seeded(pg):
    truncate(pg, "professors_catalog", "course_catalog", "source_summary", "stats_cache")
    read_models.write(pg, CATALOG, COURSES, SUMMARIES, COUNTS)


@pytest.mark.parametrize("path", [
    "/api/stats",
    "/api/professors-catalog",
    "/api/courses-catalog",
    "/api/search?q=alice",
    "/api/professors/alice-smith/full",
    "/api/courses/CS2500",
])
def test_read_endpoints_return_200(live_server, seeded, path):
    # A 500 here is a real finding: read the traceback in the pytest output. A
    # KeyError/None on an empty table means a seed row is missing (add it to
    # tests/pg/seed.py); a psycopg2 error means SQL that PostgreSQL rejects (fix it).
    resp = live_server.app.test_client().get(path)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:500]


def test_bookmark_add_is_idempotent_and_remove_deletes(live_server, seeded, pg):
    truncate(pg, "bookmarks")
    with live_server.app.app_context():
        for _ in range(2):
            assert bookmarks.add_bookmark("user-1", "professor", "alice-smith",
                                          live_server.query_one, live_server._write) == "ok"
        saved = live_server.query("SELECT id FROM bookmarks WHERE user_sub = 'user-1'")
        assert len(saved) == 1 and saved[0]["id"] >= 1
        bookmarks.remove_bookmark("user-1", "professor", "alice-smith", live_server._write)
        assert live_server.query("SELECT 1 FROM bookmarks WHERE user_sub = 'user-1'") == []


def test_usage_alert_tier_is_claimed_once_per_utc_day(live_server, pg):
    truncate(pg, "usage_alerts")
    with live_server.app.app_context():
        assert usage_alert.claim_tier(live_server._chat_write_rc, 50) is True
        assert usage_alert.claim_tier(live_server._chat_write_rc, 50) is False
        row = live_server.query_one(
            "SELECT alert_date = (now() AT TIME ZONE 'UTC')::date AS utc_today "
            "FROM usage_alerts WHERE tier = 50")
    assert row["utc_today"] is True


def test_ask_log_purge_deletes_only_rows_past_retention(live_server, pg, monkeypatch):
    # _chat_write swallows SQL errors, so only the remaining rows show the DELETE ran.
    truncate(pg, "ask_log")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO ask_log (query, mode, result_status, created_at) VALUES "
                    "('old', 'question', 'ok', now() - interval '31 days'), "
                    "('new', 'question', 'ok', now() - interval '29 days')")
    pg.commit()
    monkeypatch.setitem(live_server._ask_log_purge, "last", 0.0)
    live_server._purge_ask_log_job()
    with pg.cursor() as cur:
        cur.execute("SELECT query FROM ask_log")
        assert [r[0] for r in cur.fetchall()] == ["new"]
    pg.commit()


def test_search_finds_an_approved_alias_only(live_server, seeded, pg):
    truncate(pg, "professor_aliases")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professor_aliases (alias_key, slug, source) "
                    "VALUES ('zork', 'alice-smith', 'comment')")
    pg.commit()
    client = live_server.app.test_client()

    live_server._reset_alias_cache()
    assert client.get("/api/search?q=zork").get_json() == []

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id FROM professor_aliases")
        review_ratings.approve_alias(cur, str(cur.fetchone()["id"]))
    pg.commit()
    live_server._reset_alias_cache()
    found = client.get("/api/search?q=zork")
    assert [r["slug"] for r in found.get_json()] == ["alice-smith"]
    assert "zork" not in found.get_data(as_text=True).lower()
    truncate(pg, "professor_aliases")


def test_an_alias_hit_survives_the_100_row_cut(live_server, seeded, pg):
    truncate(pg, "professor_aliases")
    with pg.cursor() as cur:
        for i in range(105):
            cur.execute("INSERT INTO professors_catalog (slug, name, name_key, total_reviews) "
                        "VALUES (%s, %s, %s, 50)", (f"zork-{i}", f"Azork Person{i}", f"azork person{i}"))
        cur.execute("INSERT INTO professor_aliases (alias_key, slug, status, source) "
                    "VALUES ('zork', 'alice-smith', 'approved', 'manual')")
    pg.commit()
    live_server._reset_alias_cache()
    found = live_server.app.test_client().get("/api/search?q=zork&limit=20").get_json()
    assert found[0]["slug"] == "alice-smith"
    truncate(pg, "professor_aliases", "professors_catalog")
    live_server._reset_alias_cache()
