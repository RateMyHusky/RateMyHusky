"""Flask endpoints, bookmarks and usage alerts through the real pool."""

import pytest

import bookmarks
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


def _course(code, name, search_text, num_ratings):
    return {"code": code, "name": name, "department": "Computer Science", "subject": "CS",
            "search_text": search_text, "avg_rating": 4.0, "difficulty": 3.0, "num_ratings": num_ratings}


@pytest.mark.parametrize("path, key", [
    ("/api/search?type=Course&q=cs%2035", "code"),
    ("/api/courses-catalog?q=cs%2035", "code"),
    ("/api/courses-catalog?q=cs%2035&sort=recent", "code"),   # joins banner_course_offerings when present
    ("/api/search?type=Course&q=calculus", "code"),
    ("/api/courses-catalog?q=calculus", "code"),
])
def test_course_search_ranks_code_and_title_matches_above_descriptions(live_server, pg, path, key):
    courses = [
        _course("CS3500", "Object-Oriented Design", "cs3500 cs 3500 object-oriented design", 10),
        # More rated, and its description names CS 3500 as a prerequisite.
        _course("CS4500", "Software Development", "cs4500 cs 4500 software development prereq cs 3500", 90),
        _course("MATH1341", "Calculus 1 for Science and Engineering", "math1341 math 1341 calculus 1", 20),
        _course("PHYS1151", "Physics for Engineering", "phys1151 phys 1151 physics uses calculus", 80),
    ]
    truncate(pg, "professors_catalog", "course_catalog", "source_summary", "stats_cache")
    read_models.write(pg, CATALOG, courses, SUMMARIES, COUNTS)
    resp = live_server.app.test_client().get(path, headers={"User-Agent": "Mozilla/5.0"})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:500]
    body = resp.get_json()
    rows = body["courses"] if isinstance(body, dict) else body
    assert rows[0][key] == ("CS3500" if "cs" in path else "MATH1341"), rows
