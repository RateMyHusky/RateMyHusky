"""Route-level tests for /api/rate in server.py.

Env before `import server`; the pool and the query/_write helpers are stubbed so
no live DB is touched, and so are Turnstile, moderation (OpenAI, and Groq through
the FakeGroq in conftest) and the team email.
"""

import os
import time
from types import SimpleNamespace

import pytest

SECRET = "rating-secret-0123456789abcdefghijklmnop"  # gitleaks:allow
DEVICE = "a" * 32
BODY = {
    "professor": {"slug": "alice-smith"}, "course": {"code": "CS2500"},
    "term": "Fall 2025", "rating": 4, "difficulty": 3, "hours": "5-7", "grade": "A",
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
    # Set so any team email would reach fake_post: the rating route sends none.
    monkeypatch.setenv("RESEND_API_KEY", "re-test")
    server.limiter.reset()

    state = {"writes": [], "posts": [], "moderation": "allow", "network": "other",
             "turnstile": True, "turnstile_calls": 0, "seen": False, "existing": None,
             "budget": {"device": 0, "ip": 0, "shared": 0}, "scored": []}

    def fake_query_one(sql, params=()):
        if "SELECT id, status, hold_reasons, comment FROM survey_ratings" in sql:
            return state["existing"] and {"comment": None, **state["existing"]}
        if "FROM moderation_calls" in sql:
            return state["budget"]
        if "WHERE device_hash = %s LIMIT 1" in sql:
            return {"x": 1} if state["seen"] else None
        if "FROM professors_catalog" in sql:
            return {"x": 1} if params[0] == "alice-smith" else None
        if "FROM course_catalog" in sql:
            return {"x": 1} if params[0] in ("CS2500", "CS3500") else None
        if "AS taught" in sql:  # alice-smith taught CS2500, never CS3500
            return {"taught": params[:2] == ("CS2500", "alice-smith")}
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
        state["scored"].extend(texts)
        if state["moderation"] == "timeout":
            raise TimeoutError("slow")
        return [SimpleNamespace(action=state["moderation"]) for _ in texts]

    def fake_post(url, **kw):
        state["posts"].append(url)
        state["turnstile_calls"] += 1
        return SimpleNamespace(ok=True, json=lambda: {"success": state["turnstile"]})

    monkeypatch.setattr(server, "query", lambda sql, params=None: [], raising=False)
    monkeypatch.setattr(server, "query_one", fake_query_one, raising=False)
    monkeypatch.setattr(server, "_write", fake_write, raising=False)
    monkeypatch.setattr(server, "_rating_moderation_score", fake_score, raising=False)
    monkeypatch.setattr(server.http_requests, "post", fake_post)
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


def call_writes(state):
    return [w for w in state["writes"] if "INSERT INTO moderation_calls" in w[0]]


def saved(server, params, column):
    """A column of the saved rating: its params start with the new id."""
    return params[1 + server.ratings._INSERT_COLUMNS.index(column)]


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


def test_deployed_without_turnstile_is_503_not_captcha_free(rate, monkeypatch):
    # PROXY_SECRET is set only when deployed; a dropped Turnstile key there must not
    # quietly turn the CAPTCHA off.
    server, client, state, ri = rate
    monkeypatch.setattr(server, "PROXY_SECRET", "proxy-key")
    key = {"X-Proxy-Key": "proxy-key"}
    assert post(client, ri, **key).status_code == 503
    assert client.get("/api/rate/start", headers=key).status_code == 503
    assert client.get("/api/rate/professors/alice-smith", headers=key).status_code == 503
    assert state["writes"] == []
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret")
    assert post(client, ri, {"turnstileToken": "tok"}, **key).status_code == 200


def test_honeypot_gets_the_normal_response_and_writes_nothing(rate):
    server, client, state, ri = rate
    resp = post(client, ri, {"website": "http://spam.example"})
    assert resp.status_code == 200 and resp.get_json()["ok"] is True
    assert state["writes"] == [] and state["turnstile_calls"] == 0


def test_json_nested_too_deep_to_parse_is_400_not_500(rate):
    server, client, state, ri = rate
    body = "[" * 30000 + "]" * 30000   # deep enough to recurse, small enough for MAX_CONTENT_LENGTH
    resp = client.post("/api/rate", data=body, content_type="application/json")
    assert resp.status_code == 400 and resp.get_json() == {"error": "Body must be a JSON object"}
    assert state["writes"] == []


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


def test_blocked_comment_is_422_and_creates_no_pending_professor(rate):
    server, client, state, ri = rate
    state["moderation"] = "block"
    resp = post(client, ri, {"professor": {"name": "New Person", "department": "Math"},
                             "course": {"code": "ZZ9999", "name": "Brand New Course"}})
    assert resp.status_code == 422 and resp.get_json() == {"error": "comment_blocked"}
    # Only the call itself is recorded, so a blocked writer can't retry for free.
    (sql, params), = state["writes"]
    assert "INSERT INTO moderation_calls" in sql and params[2:4] == ("submit", "block")


def test_moderation_timeout_keeps_the_rating_and_queues_the_comment(rate):
    server, client, state, ri = rate
    state["moderation"] = "timeout"
    resp = post(client, ri)
    assert resp.status_code == 200 and resp.get_json() == {"ok": True, "counter": None}
    (sql, params), = rating_writes(state)
    assert saved(server, params, "status") == "accepted"
    assert saved(server, params, "hold_reasons") is None
    assert saved(server, params, "comment_check") == "unchecked"
    assert saved(server, params, "comment_check_reason") == "openai_unavailable"
    assert saved(server, params, "comment_next_check_at") is not None


def test_a_rule_match_is_422_before_any_model_call_or_write(rate):
    server, client, state, ri = rate
    for comment in ("great notes at studyhelp.com", "text me 617-555-0123", "asdfghjkl"):
        resp = post(client, ri, {"comment": comment, "professor": {"name": "New Person"}})
        assert resp.status_code == 422 and resp.get_json() == {"error": "comment_blocked"}
    assert state["writes"] == [] and state["scored"] == []


def test_groq_verdicts_mark_the_comment_and_never_hold_the_rating(rate, monkeypatch, fake_groq):
    server, client, state, ri = rate
    monkeypatch.setenv("GROQ_MODERATION_KEY", "gsk-test")
    cases = (("ALLOW", "allow", None), ("REVIEW", "review", "review"), ("Not sure.", "review", "review"),
             (TimeoutError("slow"), "unchecked", "groq_unavailable"),
             (fake_groq.RateLimited("429"), "unchecked", "groq_rate_limited"))
    for i, (reply, check, reason) in enumerate(cases):
        groq = fake_groq(reply)
        monkeypatch.setattr(server, "_groq_moderation_client", groq)
        assert post(client, ri, device=f"{i}" * 32).status_code == 200
        params = rating_writes(state)[-1][1]
        assert saved(server, params, "status") == "accepted", reply
        assert (saved(server, params, "comment_check"), saved(server, params, "comment_check_reason")) == (
            check, reason)
        (call,) = groq.calls
        assert call["model"] == "openai/gpt-oss-safeguard-20b" and call["temperature"] == 0
        assert call["messages"][1] == {"role": "user", "content": BODY["comment"]}
    assert state["scored"] == []  # never OpenAI while the Groq key is set
    assert [p[3] for s, p in call_writes(state)] == ["allow", "review", "review", "unavailable", "unavailable"]


def test_groq_block_is_422(rate, monkeypatch, fake_groq):
    server, client, state, ri = rate
    monkeypatch.setenv("GROQ_MODERATION_KEY", "gsk-test")
    monkeypatch.setattr(server, "_groq_moderation_client", fake_groq("BLOCK"))
    resp = post(client, ri)
    assert resp.status_code == 422 and resp.get_json() == {"error": "comment_blocked"}
    assert rating_writes(state) == []


def test_a_call_is_logged_without_the_comment(rate):
    server, client, state, ri = rate
    post(client, ri)
    (sql, params), = call_writes(state)
    device_hash = ri.keyed_hash(SECRET, "device", DEVICE)
    assert params[2:5] == ("submit", "allow", device_hash) and params[6] is False
    assert BODY["comment"] not in repr(params)


@pytest.mark.parametrize("setup,reason,due", [
    ("duplicate", "duplicate", False), ("burst", "burst", False), ("over_budget", "over_budget", True)])
def test_no_model_call_for_a_duplicate_a_burst_or_a_sender_over_budget(rate, monkeypatch, setup, reason, due):
    server, client, state, ri = rate
    if setup == "duplicate":
        monkeypatch.setattr(server.ratings, "duplicate_comment", lambda *a: True)
    elif setup == "burst":
        monkeypatch.setattr(server.ratings, "burst_reasons", lambda *a: ["burst_ip"])
    else:
        state["budget"] = {"device": 3, "ip": 0, "shared": 0}
    assert post(client, ri).status_code == 200
    assert state["scored"] == [] and call_writes(state) == []
    params = rating_writes(state)[0][1]
    assert saved(server, params, "comment_check") == "unchecked"
    assert saved(server, params, "comment_check_reason") == reason
    assert (saved(server, params, "comment_next_check_at") is not None) is due


def test_budgets_per_ip_and_on_shared_networks(rate):
    server, client, state, ri = rate
    state["budget"] = {"device": 0, "ip": 10, "shared": 0}
    post(client, ri)
    assert state["scored"] == []
    # Campus and Relay share addresses: one total replaces the per-IP count there.
    state["network"] = "campus"
    post(client, ri)
    assert len(state["scored"]) == 1
    state["budget"] = {"device": 0, "ip": 0, "shared": 100}
    post(client, ri)
    assert len(state["scored"]) == 1
    assert [saved(server, p, "comment_check_reason") for s, p in rating_writes(state)] == [
        "over_budget", None, "over_budget"]


def test_an_edit_that_keeps_the_text_keeps_its_check_without_a_call(rate):
    server, client, state, ri = rate
    state["existing"] = {"id": "r1", "status": "accepted", "hold_reasons": None, "comment": BODY["comment"]}
    post(client, ri, {"rating": 2})
    assert state["scored"] == [] and call_writes(state) == []
    params = rating_writes(state)[0][1]
    # Unset here, so the upsert keeps the row's own check (ratings._UPSERT_SQL).
    assert all(saved(server, params, c) is None for c in server.ratings.CHECK_COLUMNS)
    state["existing"]["comment"] = "Something else entirely about the course."
    post(client, ri)
    assert len(state["scored"]) == 1


def test_a_new_professor_is_looked_up_before_the_verdict_and_inserted_after(rate):
    server, client, state, ri = rate
    post(client, ri, {"professor": {"name": "New Person"}})
    kinds = [("moderation" if "moderation_calls" in sql else "pending" if "survey_pending" in sql else "rating")
             for sql, params in state["writes"]]
    assert kinds == ["moderation", "pending", "rating"]


def test_quick_update_keeps_an_accepted_rating_accepted(rate):
    server, client, state, ri = rate
    quick = {"opened": ri.sign_opened(SECRET, int(time.time()) - 4, ri.keyed_hash(SECRET, "device", DEVICE), False)}
    post(client, ri, quick)
    state["existing"] = {"id": "r1", "status": "accepted", "hold_reasons": None}
    post(client, ri, quick)
    state["existing"] = {"id": "r1", "status": "held", "hold_reasons": "datacenter"}
    post(client, ri, quick)
    new, edit, held = (params for sql, params in rating_writes(state))
    assert "held" in new and "too_fast" in new
    assert "accepted" in edit and "too_fast" not in edit
    assert "held" in held and "datacenter,too_fast" in held


def test_new_professor_creates_one_pending_entry_and_no_email(rate):
    # Invented names cost nothing to submit, so an email each would flood the inbox
    # and the Resend quota the feedback form shares. Reviewers use review_ratings.py list.
    server, client, state, ri = rate
    resp = post(client, ri, {"professor": {"name": "New Person", "department": "Math"}})
    assert resp.status_code == 200
    assert len([w for w in state["writes"] if "survey_pending_professors" in w[0]]) == 1
    assert [w for w in state["writes"] if "survey_pending_courses" in w[0]] == []
    # A second student naming the same professor shares the row.
    post(client, ri, {"professor": {"name": "new  PERSON"}}, device="b" * 32)
    pending_id = rating_writes(state)[0][1][1 + server.ratings._INSERT_COLUMNS.index("pending_professor_id")]
    assert rating_writes(state)[1][1][1 + server.ratings._INSERT_COLUMNS.index("pending_professor_id")] == pending_id
    assert state["posts"] == []


def test_new_course_needs_a_name_and_known_code_ignores_it(rate):
    server, client, state, ri = rate
    assert post(client, ri, {"course": {"code": "ZZ9999"}}).status_code == 400
    assert post(client, ri, {"professor": {"slug": "nobody"}}).status_code == 400
    resp = post(client, ri, {"course": {"code": "CS2500", "name": "Ignored Name"}})
    assert resp.status_code == 200
    assert [w for w in state["writes"] if "survey_pending_courses" in w[0]] == []
    resp = post(client, ri, {"course": {"code": "ZZ9999", "name": "Brand New Course"}})
    assert resp.status_code == 200
    assert len([w for w in state["writes"] if "survey_pending_courses" in w[0]]) == 1
    assert state["posts"] == []


def test_a_course_the_professor_never_taught_is_held_for_review(rate):
    # Any professor could otherwise be rated under any real code, moving that course's
    # rating and listing the professor on its page.
    server, client, state, ri = rate
    post(client, ri)
    post(client, ri, {"course": {"code": "CS3500"}})
    taught, untaught = (params for sql, params in rating_writes(state))
    assert "accepted" in taught and "unverified_pair" not in taught
    assert "held" in untaught and "unverified_pair" in untaught


def test_pending_professor_or_course_skips_the_taught_check(rate):
    # Neither counts anywhere until a reviewer approves it, so there's nothing to check.
    server, client, state, ri = rate
    post(client, ri, {"professor": {"name": "New Person"}})
    post(client, ri, {"course": {"code": "ZZ9999", "name": "Brand New Course"}})
    assert all("accepted" in params for sql, params in rating_writes(state))


def test_rate_limit_response_does_not_say_which_limit_fired(rate):
    # Naming the bucket ("20 per 1 hour" vs "300 per 1 hour") tells an attacker that
    # a fresh device token gets around it.
    server, client, state, ri = rate
    for _ in range(20):
        post(client, ri)
    resp = post(client, ri)
    assert resp.status_code == 429
    assert resp.get_json() == {"error": "Rate limit reached. Please try again later."}


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
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret")  # deployed, so Turnstile is required
    post(client, ri, {"turnstileToken": "tok"}, **{"X-Proxy-Key": "proxy-secret", "X-RMH-Client-IP": "203.0.113.9"})
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
        [{"code": "CS2500", "name": "Fundamentals of CS 1", "pending": False, "term_label": "Fall 2025",
          "rating": 4, "difficulty": 3, "hours": "5-7", "grade": "A-", "comment": "Fine."}] if "FROM survey_ratings" in sql and params[0] == device_hash else []))
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


def test_difficulty_is_saved(rate):
    server, client, state, ri = rate
    post(client, ri)
    assert rating_writes(state)[0][1][1 + server.ratings._INSERT_COLUMNS.index("difficulty")] == 3


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


def test_missing_turnstile_secret_fails_closed_on_railway(rate, monkeypatch):
    server, client, state, ri = rate
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    resp = post(client, ri, {"turnstileToken": "t"})
    assert resp.status_code == 503
    assert state["writes"] == [] and state["turnstile_calls"] == 0


def test_turnstile_token_from_another_hostname_is_403(rate, monkeypatch):
    server, client, state, ri = rate
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "ts-secret")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setattr(server, "FRONTEND_URL", "https://ratemyhusky.com")
    for host, code in (("evil.example", 403), ("ratemyhusky.com", 200)):
        monkeypatch.setattr(server.http_requests, "post", lambda *a, _h=host, **k: SimpleNamespace(
            ok=True, json=lambda: {"success": True, "hostname": _h}))
        resp = post(client, ri, {"turnstileToken": "t"})
        assert resp.status_code == code, host


def test_unreachable_siteverify_is_503_for_ratings_and_feedback(rate, monkeypatch):
    # One gate serves both forms, so Cloudflare being down fails them the same way.
    server, client, state, ri = rate
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "ts-secret")
    def down(url, **kw):
        raise server.http_requests.ConnectionError("down")
    monkeypatch.setattr(server.http_requests, "post", down)
    assert post(client, ri, {"turnstileToken": "t"}).status_code == 503
    resp = client.post("/api/feedback", json={"feedbackType": "bug", "description": "hi",
                                               "turnstileToken": "t"})
    assert resp.status_code == 503
    assert state["writes"] == []


def test_accepted_save_drops_the_professor_page_cache(rate, monkeypatch):
    server, client, state, ri = rate
    dropped = []
    monkeypatch.setattr(server, "drop_professor_pages", dropped.append)
    post(client, ri)
    assert dropped == [{"alice-smith"}]


def test_a_save_for_a_pending_professor_drops_no_page_cache(rate, monkeypatch):
    server, client, state, ri = rate
    dropped = []
    monkeypatch.setattr(server, "drop_professor_pages", dropped.append)
    post(client, ri, {"professor": {"name": "New Person", "department": "Math"}})
    assert len(rating_writes(state)) == 1 and dropped == []


def test_drop_professor_pages_drops_alias_keys_and_leaves_other_professors(monkeypatch):
    import server
    monkeypatch.setattr(server, "data_version", lambda: 7)
    server.cache_set("prof_full:a", {"identity": {"slug": "a"}})
    server.cache_set("prof_full:a-alias", {"identity": {"slug": "a"}})
    server.cache_set("prof_full:b", {"identity": {"slug": "b"}})
    server.cache_set("stats", {"x": 1})
    server.drop_professor_pages({"a"})
    assert server.cache_get("prof_full:a") is None and server.cache_get("prof_full:a-alias") is None
    assert server.cache_get("prof_full:b") == {"identity": {"slug": "b"}} and server.cache_get("stats") == {"x": 1}


def test_a_burst_drops_the_pages_of_every_professor_it_held_after_the_hold(rate, monkeypatch):
    server, client, state, ri = rate
    events = []
    monkeypatch.setattr(server.ratings, "burst_reasons", lambda *a: ["burst_ip"])
    monkeypatch.setattr(server.ratings, "hold_burst", lambda *a: events.append("hold") or {"bob-jones"})
    monkeypatch.setattr(server, "drop_professor_pages", lambda slugs: events.append(slugs))
    post(client, ri)
    # After the hold, so no request between the writes re-caches rows about to be held.
    assert events == ["hold", {"alice-smith", "bob-jones"}]


def test_an_accepted_review_edited_into_a_held_one_drops_the_page_cache(rate, monkeypatch):
    server, client, state, ri = rate
    dropped = []
    monkeypatch.setattr(server, "drop_professor_pages", dropped.append)
    state["existing"] = {"id": "r1", "status": "accepted", "hold_reasons": None}
    state["network"] = "datacenter"   # a VPN edit holds the whole rating, so the old comment must leave the page
    post(client, ri)
    (sql, params), = rating_writes(state)
    assert "held" in params
    assert dropped == [{"alice-smith"}]


def test_an_edit_after_a_rejected_comment_is_not_held(rate):
    # The new comment waits in pending like any other, so the rating keeps counting.
    server, client, state, ri = rate
    state["existing"] = {"id": "r1", "status": "accepted", "hold_reasons": None, "comment": None}
    post(client, ri)
    (sql, params), = rating_writes(state)
    assert saved(server, params, "status") == "accepted" and saved(server, params, "hold_reasons") is None
    assert saved(server, params, "comment_check") == "allow"


def test_an_old_removed_mark_no_longer_holds_an_edit(rate):
    server, client, state, ri = rate
    # A row marked by the old reject-comment, before the migration strips the mark.
    state["existing"] = {"id": "r1", "status": "accepted", "hold_reasons": "comment_removed"}
    post(client, ri)
    (sql, params), = rating_writes(state)
    assert saved(server, params, "status") == "accepted" and saved(server, params, "hold_reasons") is None
