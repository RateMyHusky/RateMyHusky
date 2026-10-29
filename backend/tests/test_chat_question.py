import os
import pytest

_JWT_SECRET = "test-secret"

@pytest.fixture
def q_client(monkeypatch):
    os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
    os.environ.setdefault("JWT_SECRET", _JWT_SECRET)
    import server
    monkeypatch.setattr(server, "_get_pool",
        lambda: (_ for _ in ()).throw(AssertionError("no DB in test")), raising=False)
    return server.app.test_client()

def _auth_headers():
    """A valid Bearer token for the account-gated question path (signed with the test secret)."""
    import jwt as pyjwt
    token = pyjwt.encode({"sub": "user-123", "email": "t@northeastern.edu",
                           "iss": "ratemyhusky", "aud": "ratemyhusky-web"}, _JWT_SECRET, algorithm="HS256")
    return {"Origin": "http://localhost:5173", "Authorization": "Bearer " + token}

def test_chat_question_returns_answer(monkeypatch, q_client):
    import server
    seen = {}
    def _fake(q, session_token, ip_hash, deps):
        seen["session_token"] = session_token  # capture what the route passed through
        return {"mode": "question", "answer": "Guha is fair.", "disclaimer": "AI-generated."}, 200
    monkeypatch.setattr(server, "handle_question", _fake)
    resp = q_client.post("/api/chat", json={"q": "is Guha hard"}, headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["mode"] == "question"
    assert "answer" in data and "disclaimer" in data
    # the route must key on the VERIFIED jwt 'sub', not a client header
    assert seen["session_token"] == "user-123"

def test_chat_question_requires_account(q_client):
    # account-gated: no Authorization token -> 401, orchestrator never reached
    resp = q_client.post("/api/chat", json={"q": "is Guha hard"},
                        headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 401

def test_chat_question_rejects_invalid_token(q_client):
    resp = q_client.post("/api/chat", json={"q": "is Guha hard"},
                        headers={"Origin": "http://localhost:5173", "Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401

def test_chat_question_kill_switch(monkeypatch, q_client):
    import server
    monkeypatch.setattr(server, "handle_question",
        lambda q, session_token, ip_hash, deps: (
            {"mode": "error", "message": "The question feature is temporarily disabled."}, 503
        ))
    monkeypatch.setattr(server, "CHAT_ENABLED", False)
    resp = q_client.post("/api/chat", json={"q": "is Guha hard"}, headers=_auth_headers())
    assert resp.status_code == 503

def test_chat_question_over_get_is_refused(q_client):
    # Questions must not travel in the query string (it lands in access logs).
    resp = q_client.get("/api/chat?q=is+Guha+hard&mode=question", headers=_auth_headers())
    assert resp.status_code == 405

def test_kill_switch_logs_nothing():
    import types
    from rag.chat_question import handle_question
    logged = []
    deps = types.SimpleNamespace(chat_enabled=False, log_fn=lambda sql, params: logged.append(params))
    _, code = handle_question("is guha hard", "user-123", "iphash", deps)
    assert code == 503 and logged == []

def test_ask_log_purge_runs_at_most_hourly(monkeypatch):
    import server
    monkeypatch.setitem(server._ask_log_purge, "last", 0.0)
    calls = []
    write = lambda sql, params: calls.append((sql, params))
    server.purge_old_ask_log(write, now=10_000)
    server.purge_old_ask_log(write, now=10_000 + 60)
    assert len(calls) == 1
    sql, params = calls[0]
    # Postgres has no DELETE ... LIMIT; the batch has to come from a subquery.
    assert sql.startswith("DELETE FROM ask_log WHERE id IN (SELECT id FROM ask_log")
    assert params[0] == server.ASK_LOG_RETENTION_DAYS
    server.purge_old_ask_log(write, now=10_000 + server.ASK_LOG_PURGE_EVERY + 1)
    assert len(calls) == 2


def test_ask_log_purge_starts_off_the_request_thread_on_railway(monkeypatch):
    import types
    import server
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    started = []
    monkeypatch.setattr(server, "Thread", lambda target, daemon: types.SimpleNamespace(
        start=lambda: started.append(target)))
    monkeypatch.setitem(server._ask_log_purge, "last", 0.0)
    with server.app.test_request_context("/api/stats"):
        server.purge_ask_log_in_background()
        assert started == []        # off Railway: never
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        server.purge_ask_log_in_background()
        server.purge_ask_log_in_background()   # claimed by the first: no second thread
    assert started == [server._purge_ask_log_job]
