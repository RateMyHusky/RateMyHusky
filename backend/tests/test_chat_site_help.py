import types

import pytest

from tests.test_chat_question import q_client, _auth_headers  # noqa: F401  (q_client is a fixture)

ORIGIN = "http://localhost:5173"


@pytest.fixture
def logged(monkeypatch):
    import server
    rows = []
    monkeypatch.setattr(server, "_chat_write", lambda sql, params: rows.append((sql, params)))
    monkeypatch.setattr(server, "CHAT_ENABLED", True)
    return rows


@pytest.fixture
def results(monkeypatch):
    """handle_question must not be reached; any call is recorded and fails the test."""
    import server
    calls = []
    def _boom(*a, **k):
        calls.append(a)
        raise AssertionError("handle_question must not be reached")
    monkeypatch.setattr(server, "handle_question", _boom)
    return calls


def test_site_question_signed_out_gets_answer_and_is_logged(q_client, logged, results):
    resp = q_client.post("/api/chat", json={"q": "how do bookmarks work"}, headers={"Origin": ORIGIN})
    assert resp.status_code == 200 and resp.get_json()["mode"] == "site_help"
    params = logged[-1][1]
    assert params[1] == "site_help" and params[3] == "site_help"   # mode, result_status
    assert params[8] is None                                        # session_token (signed out)


def test_site_question_signed_in_logs_account(q_client, logged, results):
    resp = q_client.post("/api/chat", json={"q": "how do bookmarks work"}, headers=_auth_headers())
    assert resp.status_code == 200
    assert logged[-1][1][8] == "user-123"


def test_help_id_returns_entry_without_logging(q_client, logged, results):
    resp = q_client.post("/api/chat", json={"help_id": "menu"}, headers={"Origin": ORIGIN})
    assert resp.status_code == 200
    assert resp.get_json()["mode"] == "site_help" and "menu" in resp.get_json()
    assert logged == []


def test_help_id_unknown_is_404(q_client, logged, results):
    resp = q_client.post("/api/chat", json={"help_id": "nope"}, headers={"Origin": ORIGIN})
    assert resp.status_code == 404
    assert resp.get_json() == {"mode": "error", "message": "Unknown help topic."}


def test_help_id_non_string_is_404(q_client, logged, results):
    resp = q_client.post("/api/chat", json={"help_id": 123}, headers={"Origin": ORIGIN})
    assert resp.status_code == 404


def test_non_json_body_is_harmless(q_client, logged, results):
    resp = q_client.post("/api/chat", data="x", content_type="text/plain", headers={"Origin": ORIGIN})
    assert resp.status_code == 200
    assert results == [] and logged == []


def test_kill_switch_blocks_site_help_and_logs_nothing(monkeypatch, q_client, logged, results):
    import server
    monkeypatch.setattr(server, "CHAT_ENABLED", False)
    for body in ({"q": "how do bookmarks work"}, {"help_id": "menu"}):
        resp = q_client.post("/api/chat", json=body, headers={"Origin": ORIGIN})
        assert resp.status_code == 503
    assert logged == []


def test_non_site_question_still_requires_sign_in(q_client, logged, results):
    resp = q_client.post("/api/chat", json={"q": "is Guha hard"}, headers={"Origin": ORIGIN})
    assert resp.status_code == 401
    assert logged == []


@pytest.mark.parametrize("token", ["not-a-jwt", "expired"])
def test_site_question_with_bad_token_is_answered_as_signed_out(q_client, logged, results, token):
    if token == "expired":
        import time
        import jwt as pyjwt
        from tests.test_chat_question import _JWT_SECRET
        token = pyjwt.encode({"sub": "user-123", "iss": "ratemyhusky", "aud": "ratemyhusky-web",
                              "exp": int(time.time()) - 60}, _JWT_SECRET, algorithm="HS256")
    resp = q_client.post("/api/chat", json={"q": "how do bookmarks work"},
                         headers={"Origin": ORIGIN, "Authorization": "Bearer " + token})
    assert resp.status_code == 200 and resp.get_json()["mode"] == "site_help"
    assert logged[-1][1][8] is None                                 # session_token


def test_keyword_fallback_passes_mod_filter(monkeypatch, q_client, logged):
    import server
    monkeypatch.setenv("MODERATION_ENFORCE", "true")
    seen = {}
    def _capture(q, session_token, ip_hash, deps):
        seen["deps"] = deps
        return {"mode": "question", "answer": "x", "disclaimer": "y"}, 200
    monkeypatch.setattr(server, "handle_question", _capture)
    recorded = {}
    def _kw(*args, **kwargs):
        recorded.update(kwargs)
        return {"comments": [], "professors": []}
    monkeypatch.setattr(server, "keyword_search", _kw)
    resp = q_client.post("/api/chat", json={"q": "is Guha hard"}, headers=_auth_headers())
    assert resp.status_code == 200
    seen["deps"].keyword_search_fn("x")
    # With enforcement on, the filter is a real clause; an empty one would show held comments.
    assert recorded.get("mod_filter")
    assert "mod_checked_at IS NOT NULL" in recorded["mod_filter"]
