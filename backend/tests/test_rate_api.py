"""Route-level tests for /api/rate in server.py.

Env before `import server`; the pool and the query/_write helpers are stubbed so
no live DB is touched, and so are Turnstile, moderation and the team email.
"""

import os
import time
from types import SimpleNamespace

import pytest

SECRET = "rating-secret-0123456789abcdefghijklmnop"  # gitleaks:allow
DEVICE = "a" * 32
BODY = {
    "professor": {"slug": "alice-smith"}, "course": {"code": "CS2500"},
    "term": "Fall 2025", "rating": 4, "hours": "5-7", "grade": "A",
    "comment": "Clear lectures and fair exams, would take again.",
    "website": "",
}


@pytest.fixture
def rate(monkeypatch):
    os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
    os.environ.setdefault("JWT_SECRET", "test-secret")
    import server
    import rating_identity as ri

    monkeypatch.setattr(server, "_get_pool", lambda: (_ for _ in ()).throw(AssertionError("no DB")), raising=False)
    monkeypatch.setattr(server, "cache_get", lambda key: None, raising=False)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None, raising=False)
    monkeypatch.setattr(server, "RATING_SECRET", SECRET, raising=False)
    monkeypatch.setattr(server, "PROXY_SECRET", None, raising=False)
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    server.limiter.reset()

    state = {"writes": [], "emails": [], "moderation": "allow", "network": "other",
             "turnstile": True, "turnstile_calls": 0, "seen": False}

    def fake_query_one(sql, params=()):
        if "WHERE device_hash = %s LIMIT 1" in sql:
            return {"x": 1} if state["seen"] else None
        if "FROM professors_catalog" in sql:
            return {"x": 1} if params[0] == "alice-smith" else None
        if "FROM course_catalog" in sql:
            return {"x": 1} if params[0] == "CS2500" else None
        if "count(*) AS cnt FROM survey_ratings WHERE created_at" in sql:
            return {"cnt": 3}
        if "AND status = 'pending'" in sql:  # the first insert wins, like the partial unique index
            table = sql.split("FROM ")[1].split()[0]
            ids = [p[0] for s, p in state["writes"] if f"INSERT INTO {table}" in s]
            return {"id": ids[0]} if ids else None
        return None  # banner offerings, approved courses, existing rating, duplicates, bursts

    def fake_write(sql, params=None):
        state["writes"].append((sql, params))

    def fake_score(texts):
        if state["moderation"] == "timeout":
            raise TimeoutError("slow")
        return [SimpleNamespace(action=state["moderation"]) for _ in texts]

    def fake_post(url, **kw):
        state["turnstile_calls"] += 1
        return SimpleNamespace(ok=True, json=lambda: {"success": state["turnstile"]})

    monkeypatch.setattr(server, "query", lambda sql, params=None: [], raising=False)
    monkeypatch.setattr(server, "query_one", fake_query_one, raising=False)
    monkeypatch.setattr(server, "_write", fake_write, raising=False)
    monkeypatch.setattr(server, "_rating_moderation_score", fake_score, raising=False)
    monkeypatch.setattr(server.http_requests, "post", fake_post)
    monkeypatch.setattr(server.notify, "send_team_email",
                        lambda subject, text, post=None: state["emails"].append((subject, text)) or True)
    monkeypatch.setattr(server, "_networks", SimpleNamespace(network_type=lambda ip: state["network"]))
    return server, server.app.test_client(), state, ri


def opened_for(ri, device=DEVICE, minted=False):
    return ri.sign_opened(SECRET, int(time.time()) - 60, ri.keyed_hash(SECRET, "device", device), minted)


def post(client, ri, body=None, device=DEVICE, minted=False, **headers):
    payload = dict(BODY, opened=opened_for(ri, device, minted))
    payload.update(body or {})
    client.set_cookie("rmh_device", device, path="/api")
    return client.post("/api/rate", json=payload, headers=headers)


def rating_writes(state):
    return [w for w in state["writes"] if "INSERT INTO survey_ratings" in w[0]]


def test_start_sets_a_device_cookie_and_signs_opened(rate):
    server, client, state, ri = rate
    resp = client.get("/api/rate/start")
    assert resp.status_code == 200
    cookie = resp.headers["Set-Cookie"]
    for part in ("rmh_device=", "HttpOnly", "Secure", "SameSite=Lax", "Path=/api"):
        assert part in cookie
    data = resp.get_json()
    assert cookie.split("rmh_device=")[1].split(";")[0] == data["deviceToken"]
    assert data["counter"] is None
    assert resp.headers["Cache-Control"] == "no-store"
    device_hash = ri.keyed_hash(SECRET, "device", data["deviceToken"])
    fill, minted = ri.read_opened(SECRET, data["opened"], device_hash, int(time.time()) + 5)
    assert fill is not None and minted is True
    again = client.get("/api/rate/start")
    assert again.get_json()["deviceToken"] == data["deviceToken"]


def test_start_adopts_the_localstorage_mirror_when_the_cookie_is_gone(rate):
    server, client, state, ri = rate
    resp = client.get("/api/rate/start", headers={"X-Rmh-Device": DEVICE})
    assert resp.get_json()["deviceToken"] == DEVICE
    assert f"rmh_device={DEVICE}" in resp.headers["Set-Cookie"]
    # The query string ends up in access logs, so it's never read.
    client.delete_cookie("rmh_device", path="/api")
    assert client.get(f"/api/rate/start?device={DEVICE}").get_json()["deviceToken"] != DEVICE


def test_submit_without_secret_is_503(rate, monkeypatch):
    server, client, state, ri = rate
    monkeypatch.setattr(server, "RATING_SECRET", None)
    assert post(client, ri).status_code == 503
    assert client.get("/api/rate/start").status_code == 503
    assert client.get("/api/rate/professors/alice-smith").status_code == 503
    assert state["writes"] == []
    monkeypatch.setattr(server, "RATING_SECRET", "short-secret")
    assert post(client, ri).status_code == 503
    assert client.get("/api/rate/start").status_code == 503
    assert client.get("/api/rate/professors/alice-smith").status_code == 503
    assert state["writes"] == []


def test_honeypot_gets_the_normal_response_and_writes_nothing(rate):
    server, client, state, ri = rate
    resp = post(client, ri, {"website": "http://spam.example"})
    assert resp.status_code == 200 and resp.get_json()["ok"] is True
    assert state["writes"] == [] and state["turnstile_calls"] == 0


def test_validation_error_is_400(rate):
    server, client, state, ri = rate
    resp = post(client, ri, {"rating": 9})
    assert resp.status_code == 400 and "error" in resp.get_json()


def test_turnstile_failure_is_403_and_writes_nothing(rate, monkeypatch):
    server, client, state, ri = rate
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "ts-secret")
    assert post(client, ri).status_code == 400  # token missing
    state["turnstile"] = False
    resp = post(client, ri, {"turnstileToken": "t"})
    assert resp.status_code == 403
    assert state["writes"] == []


def test_blocked_comment_is_422_and_creates_no_pending_professor_or_email(rate):
    server, client, state, ri = rate
    state["moderation"] = "block"
    resp = post(client, ri, {"professor": {"name": "New Person", "department": "Math"},
                             "course": {"code": "ZZ9999", "name": "Brand New Course"}})
    assert resp.status_code == 422 and resp.get_json() == {"error": "comment_blocked"}
    assert state["writes"] == [] and state["emails"] == []


def test_moderation_timeout_holds(rate):
    server, client, state, ri = rate
    state["moderation"] = "timeout"
    resp = post(client, ri)
    assert resp.status_code == 200 and resp.get_json() == {"ok": True, "counter": None}
    (sql, params), = rating_writes(state)
    assert "held" in params
    assert "moderation_unavailable" in params


def test_new_professor_creates_one_pending_entry_and_one_email(rate):
    server, client, state, ri = rate
    resp = post(client, ri, {"professor": {"name": "New Person", "department": "Math"}})
    assert resp.status_code == 200
    assert len([w for w in state["writes"] if "survey_pending_professors" in w[0]]) == 1
    assert [w for w in state["writes"] if "survey_pending_courses" in w[0]] == []
    (subject, text), = state["emails"]
    assert subject == "[RateMyHusky] New professor to review: New Person"
    assert "Math" in text and "python review_ratings.py list" in text
    # A second student naming the same professor shares the row and sends no email.
    post(client, ri, {"professor": {"name": "new  PERSON"}}, device="b" * 32)
    assert len(state["emails"]) == 1
    pending_id = rating_writes(state)[0][1][1 + server.ratings._INSERT_COLUMNS.index("pending_professor_id")]
    assert rating_writes(state)[1][1][1 + server.ratings._INSERT_COLUMNS.index("pending_professor_id")] == pending_id


def test_team_email_is_sent_after_the_rating_is_saved(rate, monkeypatch):
    server, client, state, ri = rate
    saved_at_send = []
    monkeypatch.setattr(server.notify, "send_team_email",
                        lambda subject, text, post=None: saved_at_send.append(len(rating_writes(state))))
    post(client, ri, {"course": {"code": "ZZ9999", "name": "Brand New Course"}})
    assert saved_at_send == [1]


def test_new_course_needs_a_name_and_known_code_ignores_it(rate):
    server, client, state, ri = rate
    assert post(client, ri, {"course": {"code": "ZZ9999"}}).status_code == 400
    assert post(client, ri, {"professor": {"slug": "nobody"}}).status_code == 400
    resp = post(client, ri, {"course": {"code": "CS2500", "name": "Ignored Name"}})
    assert resp.status_code == 200
    assert [w for w in state["writes"] if "survey_pending_courses" in w[0]] == []
    resp = post(client, ri, {"course": {"code": "ZZ9999", "name": "Brand New Course"}})
    assert resp.status_code == 200
    assert state["emails"][-1][0] == "[RateMyHusky] New course to review: ZZ9999"


def test_accepted_and_held_responses_are_identical(rate):
    server, client, state, ri = rate
    accepted = post(client, ri)
    state["moderation"] = "review"
    held = post(client, ri, device="b" * 32)
    assert accepted.status_code == held.status_code == 200
    assert accepted.get_json() == held.get_json()


def test_no_raw_ip_is_written(rate, monkeypatch):
    server, client, state, ri = rate
    monkeypatch.setattr(server, "PROXY_SECRET", "proxy-secret")
    post(client, ri, **{"X-Proxy-Key": "proxy-secret", "X-RMH-Client-IP": "203.0.113.9"})
    assert rating_writes(state)
    for sql, params in state["writes"]:
        assert "203.0.113.9" not in repr(params)


def test_shared_network_is_exempt_from_the_ip_limit(rate):
    server, client, state, ri = rate
    for network, shared in (("campus", True), ("relay", True), ("other", False)):
        state["network"] = network
        with server.app.test_request_context("/api/rate"):
            assert server._shared_network() is shared


def test_network_type_is_looked_up_once_per_submit(rate, monkeypatch):
    server, client, state, ri = rate
    lookups = []
    monkeypatch.setattr(server, "_networks",
                        SimpleNamespace(network_type=lambda ip: lookups.append(ip) or "other"))
    assert post(client, ri).status_code == 200
    assert len(lookups) == 1


def test_professor_context_uses_cookie_device_and_404s_unknown(rate):
    server, client, state, ri = rate
    assert client.get("/api/rate/professors/nobody").status_code == 404
    resp = client.get("/api/rate/professors/alice-smith")
    assert resp.status_code == 200 and resp.headers["Cache-Control"] == "no-store"
    assert resp.get_json() == {"ratedCourses": []}
    assert "Set-Cookie" not in resp.headers


def test_professor_context_reads_the_mirror_header_without_a_cookie(rate, monkeypatch):
    server, client, state, ri = rate
    device_hash = ri.keyed_hash(SECRET, "device", DEVICE)
    monkeypatch.setattr(server, "query", lambda sql, params=None: (
        [{"course_code": "CS2500", "name": "Fundamentals of CS 1", "term_label": "Fall 2025",
          "rating": 4, "hours": "5-7", "grade": "A-", "comment": "Fine."}] if "FROM survey_ratings" in sql and params[0] == device_hash else []))
    assert client.get("/api/rate/professors/alice-smith").get_json()["ratedCourses"] == []
    resp = client.get("/api/rate/professors/alice-smith", headers={"X-Rmh-Device": DEVICE})
    assert [c["code"] for c in resp.get_json()["ratedCourses"]] == ["CS2500"]


def test_new_device_follows_the_opened_token_and_cookie_is_set(rate):
    server, client, state, ri = rate
    state["seen"] = True  # the device has rated before
    resp = post(client, ri)
    assert "rmh_device=" in resp.headers["Set-Cookie"]
    assert rating_writes(state)[0][1][14] is False  # new_device column
    post(client, ri, device="c" * 32, minted=True)
    assert rating_writes(state)[1][1][14] is True


def test_forged_token_without_prior_rows_is_a_new_device(rate):
    server, client, state, ri = rate
    col = 1 + server.ratings._INSERT_COLUMNS.index("new_device")  # params start with the new id
    post(client, ri, device="d" * 32)  # well-formed, never seen, opened token not minted
    assert rating_writes(state)[0][1][col] is True
    state["seen"] = True
    post(client, ri, device="d" * 32)
    assert rating_writes(state)[1][1][col] is False


def test_limit_key_uses_the_body_token_when_there_is_no_cookie(rate):
    server, client, state, ri = rate
    expect = ri.keyed_hash(SECRET, "device", DEVICE) + "|"
    with server.app.test_request_context("/api/rate", method="POST", json={"deviceToken": DEVICE}):
        assert server._rating_limit_key().startswith(expect)
    for body in ({"deviceToken": "nope"}, {}, [1], None):
        with server.app.test_request_context("/api/rate", method="POST", json=body):
            assert "|" not in server._rating_limit_key()
