import os
import pytest

@pytest.fixture
def chat_client(monkeypatch):
    os.environ.setdefault("CRDB_DATABASE_URL", "postgresql://stub")
    os.environ.setdefault("JWT_SECRET", "test-secret")
    import server
    # Stop the real pool from ever opening a connection during this test.
    monkeypatch.setattr(server, "_get_pool", lambda: (_ for _ in ()).throw(AssertionError("no DB in test")), raising=False)
    monkeypatch.setattr(server, "keyword_search",
        lambda q, qf, pf, limit=20, mod_filter="": {
            "comments": [{"source_id": "c1", "professor_slugs": ["ada-lovelace"],
                "snippet": "great grader", "sentiments": {"ada-lovelace": {"sentiment": "positive", "score": 0.6}},
                "subreddit": "NEU", "permalink": "/r/x", "rank": 0.9}],
            "professors": [{"slug": "ada-lovelace", "name": "Ada Lovelace"}],
        })
    return server.app.test_client()

def test_chat_keyword_returns_results(chat_client):
    resp = chat_client.get("/api/chat?q=grader&mode=keyword",
                           headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["mode"] == "keyword"
    assert isinstance(data["results"][0]["professor_slugs"], list)
    assert "ada-lovelace" in data["results"][0]["professor_slugs"]
    assert "professors" in data
    assert data["professors"][0]["slug"] == "ada-lovelace"

def test_chat_question_mode_requires_account(chat_client):
    # question mode is account-gated: an unauthenticated request is rejected (401)
    # before the orchestrator is ever reached.
    resp = chat_client.get("/api/chat?q=is+Guha+hard&mode=question",
                           headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 401

def test_chat_short_query(chat_client):
    resp = chat_client.get("/api/chat?q=x", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.get_json() == {"mode": "keyword", "results": []}

def test_chat_bad_limit_defaults(chat_client):
    resp = chat_client.get("/api/chat?q=grader&mode=keyword&limit=abc",
                           headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.get_json()["mode"] == "keyword"
