"""/api/professors/<slug>/full through Flask, plus the JSON error handlers."""

import datetime
import os

import jwt
import psycopg2.errors
import pytest

os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
import server  # noqa: E402

from tests.test_professor_full import CATALOG, REVIEWS, SUMMARY_ROWS  # noqa: E402

TEST_SECRET = "test-secret-0123456789abcdefghijklmnop"  # gitleaks:allow


def _token():
    return jwt.encode({"sub": "u1", "email": "t@husky.neu.edu", "iss": "ratemyhusky", "aud": "ratemyhusky-web",
                       "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)},
                      TEST_SECRET, algorithm="HS256")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "JWT_SECRET", TEST_SECRET, raising=False)
    monkeypatch.setattr(server, "_get_pool",
                        lambda: (_ for _ in ()).throw(AssertionError("no DB in test")), raising=False)
    monkeypatch.setattr(server, "cache_get", lambda key: None, raising=False)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None, raising=False)
    monkeypatch.setattr(server.limiter, "enabled", False)
    # The department hub map is one process-wide cache entry shared by every professor,
    # not part of a page's own reads; test_department_link covers it.
    monkeypatch.setattr(server, "_department_hub_map", lambda: {})
    calls = []

    def fake_query(sql, params=()):
        calls.append(sql)
        s = " ".join(sql.split())
        if "FROM professors_catalog WHERE slug" in s:
            return [dict(CATALOG)] if params[0] == "olin-guha" else []
        if "FROM professors_catalog WHERE name_key" in s:
            return []
        if "FROM rmp_reviews" in s:
            return [dict(r) for r in REVIEWS]
        if "FROM source_summary" in s:
            return [dict(r) for r in SUMMARY_ROWS]
        if "FROM reddit_mentions" in s:
            return []
        if "FROM survey_ratings" in s:
            return []
        if "FROM banner_course_instructors" in s:
            return []
        raise AssertionError(f"unexpected query: {s}")

    monkeypatch.setattr(server, "query", fake_query, raising=False)
    c = server.app.test_client()
    c.calls = calls
    return c


def test_full_serves_the_contract(client):
    resp = client.get("/api/professors/olin-guha/full")
    assert resp.status_code == 200
    assert set(resp.get_json()) == {"version", "identity", "summary", "sources", "courses", "redditMentions",
                                    "awards", "lastTaught"}


def test_full_is_identical_for_anonymous_and_signed_in(client):
    anon = client.get("/api/professors/olin-guha/full")
    authed = client.get("/api/professors/olin-guha/full",
                        headers={"Authorization": f"Bearer {_token()}"})
    assert anon.get_data() == authed.get_data()
    assert anon.headers["Vary"] == authed.headers["Vary"]
    assert "Authorization" in [v.strip() for v in anon.headers["Vary"].split(",")]
    assert anon.headers["Cache-Control"] == "public, max-age=3600"
    assert authed.headers["Cache-Control"] == "private, max-age=3600"


def test_full_makes_at_most_six_round_trips(client):
    client.get("/api/professors/olin-guha/full")
    assert len(client.calls) <= 6


@pytest.mark.parametrize("shown, secret", [(False, TEST_SECRET), (True, None)])
def test_full_reads_no_student_reviews_unless_shown_and_secret_set(client, monkeypatch, shown, secret):
    monkeypatch.setattr(server, "SHOW_STUDENT_REVIEWS", shown)
    monkeypatch.setattr(server, "RATING_SECRET", secret)
    client.get("/api/professors/olin-guha/full")
    assert not any("survey_ratings" in sql for sql in client.calls)


def test_full_reads_student_reviews_when_shown(client, monkeypatch):
    monkeypatch.setattr(server, "SHOW_STUDENT_REVIEWS", True)
    monkeypatch.setattr(server, "RATING_SECRET", TEST_SECRET)
    client.get("/api/professors/olin-guha/full")
    assert any("survey_ratings" in sql for sql in client.calls)


def test_unknown_professor_is_a_json_404(client):
    resp = client.get("/api/professors/nobody/full")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "Professor not found"}


def test_removed_professor_routes_are_json_404s(client):
    for path in ("/api/professors/olin-guha", "/api/professors/olin-guha/reviews"):
        resp = client.get(path)
        assert resp.status_code == 404, path
        assert "error" in resp.get_json()


def test_unhandled_database_error_is_a_json_500_not_a_crash(client, monkeypatch):
    def broken(sql, params=()):
        raise psycopg2.errors.UndefinedTable("relation does not exist")
    monkeypatch.setattr(server, "query", broken, raising=False)
    resp = client.get("/api/stats")
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "Internal server error"}


def test_unknown_route_is_a_json_404(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert "error" in resp.get_json()


def test_wrong_method_is_a_json_405(client):
    resp = client.post("/api/stats")
    assert resp.status_code == 405
    assert "error" in resp.get_json()


def _spy_cache(monkeypatch, payload):
    sets = []
    monkeypatch.setattr(server, "build_payload", lambda *a, **k: dict(payload))
    monkeypatch.setattr(server, "cache_set", lambda key, data: sets.append(key))
    return sets


def test_failed_history_payload_is_served_but_not_cached(client, monkeypatch):
    sets = _spy_cache(monkeypatch, {"version": 2, "identity": {"slug": "olin-guha"}, "_partial": True})
    resp = client.get("/api/professors/olin-guha/full")
    assert resp.status_code == 200
    assert "_partial" not in resp.get_json()
    assert sets == []
    assert resp.headers["Cache-Control"] == "no-store"   # nor by the CDN or browser


def test_clean_payload_is_cached(client, monkeypatch):
    sets = _spy_cache(monkeypatch, {"version": 2, "identity": {"slug": "olin-guha"}})
    resp = client.get("/api/professors/olin-guha/full")
    assert resp.status_code == 200
    assert sets == ["prof_full:olin-guha"]
    assert resp.headers["Cache-Control"] == "public, max-age=3600"
