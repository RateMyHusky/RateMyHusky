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
    token = pyjwt.encode({"sub": "user-123", "email": "t@northeastern.edu"}, _JWT_SECRET, algorithm="HS256")
    return {"Origin": "http://localhost:5173", "Authorization": "Bearer " + token}

def test_chat_question_returns_answer(monkeypatch, q_client):
    import server
    seen = {}
    def _fake(q, session_token, ip_hash, deps):
        seen["session_token"] = session_token  # capture what the route passed through
        return {"mode": "question", "answer": "Guha is fair.", "disclaimer": "AI-generated."}, 200
    monkeypatch.setattr(server, "handle_question", _fake)
    resp = q_client.get("/api/chat?q=is+Guha+hard&mode=question", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["mode"] == "question"
    assert "answer" in data and "disclaimer" in data
    # the route must key on the VERIFIED jwt 'sub', not a client header
    assert seen["session_token"] == "user-123"

def test_chat_question_requires_account(q_client):
    # account-gated: no Authorization token -> 401, orchestrator never reached
    resp = q_client.get("/api/chat?q=is+Guha+hard&mode=question",
                        headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 401

def test_chat_question_rejects_invalid_token(q_client):
    resp = q_client.get("/api/chat?q=is+Guha+hard&mode=question",
                        headers={"Origin": "http://localhost:5173", "Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401

def test_chat_question_kill_switch(monkeypatch, q_client):
    import server
    monkeypatch.setattr(server, "handle_question",
        lambda q, session_token, ip_hash, deps: (
            {"mode": "error", "message": "The question feature is temporarily disabled."}, 503
        ))
    monkeypatch.setattr(server, "CHAT_ENABLED", False)
    resp = q_client.get("/api/chat?q=is+Guha+hard&mode=question", headers=_auth_headers())
    assert resp.status_code == 503
