"""Route-level tests for GET/PUT /api/profile (same fixture pattern as test_bookmarks_api.py)."""

import os

import pytest

import programs
import rating_identity
from tests.test_bookmarks_api import TEST_SECRET, auth_headers  # noqa: F401

RATING_SECRET = "rating-secret-0123456789abcdefghijklmnop"  # gitleaks:allow
M1 = sorted(programs.MAJORS)[0]


@pytest.fixture
def pf_client(monkeypatch):
    os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
    os.environ.setdefault("JWT_SECRET", "test-secret")
    import server
    monkeypatch.setattr(server, "JWT_SECRET", TEST_SECRET, raising=False)
    monkeypatch.setattr(server, "RATING_SECRET", RATING_SECRET, raising=False)
    monkeypatch.setattr(server, "_get_pool", lambda: (_ for _ in ()).throw(AssertionError("no DB in test")), raising=False)

    state = {"row": None, "writes": []}

    def fake_query_one(sql, params=()):
        if "FROM student_profiles" in sql:
            return state["row"]
        raise AssertionError(f"unexpected query_one: {sql}")

    def fake_write(sql, params=None):
        state["writes"].append((sql, params))

    monkeypatch.setattr(server, "query_one", fake_query_one, raising=False)
    monkeypatch.setattr(server, "_write", fake_write, raising=False)
    return server.app.test_client(), state


def test_get_requires_sign_in(pf_client):
    client, _ = pf_client
    resp = client.get("/api/profile")
    assert resp.status_code == 401 and resp.get_json() == {"error": "Sign in required"}


def test_put_requires_sign_in(pf_client):
    client, state = pf_client
    resp = client.put("/api/profile", json={"gradYear": None, "majors": [], "minors": []})
    assert resp.status_code == 401 and resp.get_json() == {"error": "Sign in required"}
    assert state["writes"] == []


def test_get_without_a_row(pf_client):
    client, _ = pf_client
    resp = client.get("/api/profile", headers=auth_headers())
    assert resp.get_json() == {"exists": False, "optedOut": False}


def test_get_with_an_opted_out_row(pf_client):
    client, state = pf_client
    state["row"] = {"tracking_opt_out": True}
    resp = client.get("/api/profile", headers=auth_headers())
    assert resp.get_json() == {"exists": True, "optedOut": True}


def test_put_valid_writes_once_for_the_token_sub(pf_client):
    client, state = pf_client
    import datetime
    year = datetime.datetime.now(datetime.timezone.utc).year + 2
    resp = client.put("/api/profile", headers=auth_headers(sub="u-9"),
                      json={"gradYear": year, "majors": [M1], "minors": []})
    assert resp.status_code == 200 and resp.get_json() == {"ok": True}
    assert len(state["writes"]) == 1
    assert state["writes"][0][1][:3] == ("u-9", "undergrad", year)


def test_put_grad_student_writes_level_grad(pf_client):
    client, state = pf_client
    resp = client.put("/api/profile", headers=auth_headers(sub="u-9"),
                      json={"gradYear": None, "majors": [], "minors": []})
    assert resp.status_code == 200
    assert state["writes"][0][1][:3] == ("u-9", "grad", None)


def test_put_invalid_is_400_with_no_write(pf_client):
    client, state = pf_client
    resp = client.put("/api/profile", headers=auth_headers(),
                      json={"gradYear": 2028, "majors": [], "minors": []})
    assert resp.status_code == 400 and resp.get_json()["error"]
    assert state["writes"] == []


VIEW = {"itemType": "professor", "itemKey": "alice-smith", "visibleSeconds": 30, "reachedSection": True, "courseFilter": None}


@pytest.fixture
def view_client(pf_client, monkeypatch):
    import server
    client, state = pf_client

    def fake_query_one(sql, params=()):
        if "FROM student_profiles" in sql:
            return state["row"]
        return {"x": 1} if params == ("alice-smith",) else None

    monkeypatch.setattr(server, "query_one", fake_query_one, raising=False)
    return client, state


def test_view_requires_sign_in(view_client):
    client, state = view_client
    resp = client.post("/api/views", json=VIEW)
    assert resp.status_code == 401 and resp.get_json() == {"error": "Sign in required"}
    assert state["writes"] == []


def test_view_bad_body_is_400(view_client):
    client, state = view_client
    resp = client.post("/api/views", headers=auth_headers(), json={**VIEW, "visibleSeconds": True})
    assert resp.status_code == 400 and resp.get_json()["error"]
    assert state["writes"] == []


def test_view_without_a_profile_is_204_and_stores_nothing(view_client):
    client, state = view_client
    resp = client.post("/api/views", headers=auth_headers(), json=VIEW)
    assert resp.status_code == 204 and resp.data == b""
    assert state["writes"] == []


def test_view_with_a_profile_is_204_and_stores_one_row(view_client):
    client, state = view_client
    state["row"] = {"tracking_opt_out": False}
    resp = client.post("/api/views", headers=auth_headers(sub="u-3"), json=VIEW)
    assert resp.status_code == 204 and resp.data == b""
    assert len(state["writes"]) == 1
    # stored under its own keyed hash, never the sub, and never the rating account hash
    viewer = rating_identity.keyed_hash(RATING_SECRET, "viewer", "u-3")
    assert state["writes"][0][1][0] == viewer
    assert "u-3" not in state["writes"][0][1][:-1]
    assert viewer != rating_identity.keyed_hash(RATING_SECRET, "account", "u-3")


def test_view_without_a_rating_secret_is_503_and_stores_nothing(view_client, monkeypatch):
    import server
    client, state = view_client
    state["row"] = {"tracking_opt_out": False}
    for secret in (None, "too-short"):
        monkeypatch.setattr(server, "RATING_SECRET", secret)
        resp = client.post("/api/views", headers=auth_headers(), json=VIEW)
        assert resp.status_code == 503 and resp.get_json()["error"]
    assert state["writes"] == []


def test_views_have_a_daily_cap_per_student(view_client, monkeypatch):
    import server
    monkeypatch.setattr(server.limiter, "enabled", True)
    server.limiter.reset()
    client, state = view_client
    state["row"] = {"tracking_opt_out": False}
    # past the per-minute cap, so only the per-day cap (500) can be what stops a student
    now = [1000.0]
    monkeypatch.setattr("time.time", lambda: now[0])
    codes = []
    for i in range(501):
        now[0] += 2
        codes.append(client.post("/api/views", headers=auth_headers(sub="u-flood"), json=VIEW).status_code)
    assert codes[:500] == [204] * 500 and codes[500] == 429
    server.limiter.reset()


def test_view_of_an_unknown_item_is_400(view_client):
    client, state = view_client
    state["row"] = {"tracking_opt_out": False}
    resp = client.post("/api/views", headers=auth_headers(), json={**VIEW, "itemKey": "nobody"})
    assert resp.status_code == 400 and resp.get_json()["error"]
    assert state["writes"] == []


def test_limits_are_per_student_not_per_shared_ip(pf_client, monkeypatch):
    import server
    monkeypatch.setattr(server.limiter, "enabled", True)
    server.limiter.reset()
    client, _ = pf_client
    campus_ip = {"REMOTE_ADDR": "10.9.8.7"}

    def get(sub):
        return client.get("/api/profile", headers=auth_headers(sub=sub), environ_overrides=campus_ip)

    assert all(get("u-a").status_code == 200 for _ in range(30))
    assert get("u-a").status_code == 429
    assert get("u-b").status_code == 200   # same IP, own budget
    server.limiter.reset()
