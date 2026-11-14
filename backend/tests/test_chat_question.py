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
    def _fake(q, session_token, deps):
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

def test_chat_question_over_get_is_refused(q_client):
    # Questions must not travel in the query string (it lands in access logs).
    resp = q_client.get("/api/chat?q=is+Guha+hard&mode=question", headers=_auth_headers())
    assert resp.status_code == 405

def test_ask_log_purge_runs_at_most_hourly(monkeypatch):
    import server
    monkeypatch.setitem(server._ask_log_purge, "last", 0.0)
    calls = []
    write = lambda sql, params: calls.append((sql, params))
    server.purge_old_ask_log(write, now=10_000)
    server.purge_old_ask_log(write, now=10_000 + 60)
    assert len(calls) == 2          # one run: the delete and the ip_hash clear
    sql, params = calls[0]
    # Postgres has no DELETE ... LIMIT; the batch has to come from a subquery.
    assert sql.startswith("DELETE FROM ask_log WHERE id IN (SELECT id FROM ask_log")
    assert params[0] == server.ASK_LOG_RETENTION_DAYS
    # Rows from before Ask stopped storing IPs lose their hash.
    assert calls[1][0] == "UPDATE ask_log SET ip_hash = NULL WHERE ip_hash IS NOT NULL"
    server.purge_old_ask_log(write, now=10_000 + server.ASK_LOG_PURGE_EVERY + 1)
    assert len(calls) == 4


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


def _disambiguation_deps(**over):
    import types
    base = dict(
        num_keys=1,
        log_fn=lambda sql, params: None,
        query_one_fn=lambda sql, params=(): None,
        gate_fn=lambda q: {"ok": True, "status": "ok", "professors_or_courses": ["Lee"],
                           "professor_or_course": "Lee", "message": None},
        prof_search_fn=lambda hint, limit=None: [
            {"name": "Ann Lee", "department": "Khoury"},
            {"name": "Bo Lee", "department": "Physics"}],
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def test_disambiguation_payload_names_the_ambiguous_hint():
    from rag.chat_question import handle_question
    payload, code = handle_question("is Lee hard", "user-123", _disambiguation_deps())
    assert code == 200 and payload["mode"] == "disambiguation"
    assert payload["ambiguous"] == "Lee"
    assert [m["pick"] for m in payload["matches"]] == ["Ann Lee", "Bo Lee"]
    assert all(m["pick"] == m["name"] for m in payload["matches"])


def test_course_disambiguation_payload_picks_the_course_code():
    from rag.chat_question import handle_question
    deps = _disambiguation_deps(
        gate_fn=lambda q: {"ok": True, "status": "ok", "professors_or_courses": ["Data Science"],
                           "professor_or_course": "Data Science", "message": None},
        cache_get_fn=lambda key: None,
        retrieve_fn=lambda q, hint: {
            "kind": "course_disambiguation",
            "matches": [{"code": "DS2000", "name": "Intro to Data Science", "department": "Khoury"},
                        {"code": "DS3000", "name": "Foundations of Data Science", "department": "Khoury"}],
            "entity_key": None, "course_code": None, "professor_slug": None,
            "facts": {}, "comments": [], "comment_count": 0},
        num_keys=1)
    payload, code = handle_question("is data science hard", "user-123", deps)
    assert code == 200 and payload["mode"] == "disambiguation"
    assert payload["ambiguous"] == "Data Science"
    assert [m["pick"] for m in payload["matches"]] == ["DS2000", "DS3000"]


def test_site_help_llm_returns_menu_logged_as_site_help():
    from rag.chat_question import handle_question
    logged = []
    deps = _disambiguation_deps(
        log_fn=lambda sql, params: logged.append(params),
        query_one_fn=lambda sql, params=(): {"c": 0},
        gate_fn=lambda q: {"ok": False, "status": "site_help_llm", "professors_or_courses": [],
                           "professor_or_course": None, "message": None,
                           "classified": True, "tokens_used": 350})
    payload, code = handle_question("what does this thing do", "user-123", deps)
    assert code == 200
    assert payload["mode"] == "site_help" and payload["id"] == "menu"
    # log_ask params: (query, mode, slug, result_status, ..., flagged)
    assert logged[-1][1] == "site_help"
    assert logged[-1][3] == "site_help_llm"
    assert logged[-1][6] == 350        # the classifier call is metered
    assert logged[-1][-1] is False


def test_server_wires_the_conduct_check(monkeypatch, q_client):
    import server
    seen = {}
    def _capture(q, session_token, deps):
        seen["deps"] = deps
        return {"mode": "question", "answer": "x", "disclaimer": "y"}, 200
    monkeypatch.setattr(server, "handle_question", _capture)
    resp = q_client.post("/api/chat", json={"q": "is Guha hard"}, headers=_auth_headers())
    assert resp.status_code == 200
    assert seen["deps"].conduct_check_fn == server._chat_adapter.check_conduct
