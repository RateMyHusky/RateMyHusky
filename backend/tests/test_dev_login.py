"""The local-dev sign-in (/api/auth/dev-login): off unless DEV_LOGIN=1 and not on
Railway, and when on it issues the same kind of session token Google sign-in does."""
import time

import pytest
import server

PATH = server.DEV_LOGIN_PATH
MISSING = "/api/auth/no-such-route"


@pytest.fixture
def client(monkeypatch):
    server.limiter.reset()
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.setenv("DEV_LOGIN", "1")
    yield server.app.test_client()
    server.limiter.reset()


def _login(client, **body):
    resp = client.post(PATH, json=body)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["token"]


def _answer(resp):
    return resp.status_code, resp.get_data(), resp.headers.get("Allow")


def _same_as_missing(client):
    """Every method, and a burst past the route's own limit, answers as a missing path does."""
    for method in ("get", "post", "put", "delete", "options"):
        assert _answer(getattr(client, method)(PATH)) == _answer(getattr(client, method)(MISSING)), method
    server.limiter.reset()
    burst = [client.post(PATH, json={}).status_code for _ in range(25)]
    server.limiter.reset()
    assert burst == [client.post(MISSING, json={}).status_code for _ in range(25)]


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes"])
def test_off_without_the_opt_in(client, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("DEV_LOGIN", raising=False)
    else:
        monkeypatch.setenv("DEV_LOGIN", value)
    _same_as_missing(client)


@pytest.mark.parametrize("env", ["production", "dev"])
def test_off_on_railway_even_with_the_opt_in(client, monkeypatch, env):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", env)
    _same_as_missing(client)


def test_issues_a_session_the_backend_accepts(client):
    token = _login(client)
    claims = server.decode_session_token(token)
    assert claims["sub"] == "dev-login:dev"
    assert claims["email"] == "dev@husky.neu.edu"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.get_json() == {"email": "dev@husky.neu.edu", "name": "Dev User", "picture": ""}


def test_no_body_signs_in_as_the_default_account(client):
    resp = client.post(PATH)
    assert resp.status_code == 200
    assert server.decode_session_token(resp.get_json()["token"])["sub"] == "dev-login:dev"


def test_get_is_not_allowed_when_on(client):
    assert client.get(PATH).status_code == 405


def test_token_expires_like_a_google_session(client):
    claims = server.decode_session_token(_login(client))
    remaining = claims["exp"] - time.time()
    assert server.SESSION_DAYS * 86400 - 60 < remaining <= server.SESSION_DAYS * 86400


def test_as_picks_a_separate_account(client):
    ben = server.decode_session_token(_login(client, **{"as": "ben"}))
    dev = server.decode_session_token(_login(client))
    assert ben["sub"] == "dev-login:ben" and ben["email"] == "ben@husky.neu.edu"
    assert ben["name"] == "Dev ben"
    assert ben["sub"] != dev["sub"]


@pytest.mark.parametrize("name", ["Ben", "a b", "x" * 33, "-x", "../x", "ben@evil.com", "ben\n", "", 5, None, ["ben"]])
def test_as_refuses_names_outside_the_allowed_shape(client, name):
    # The name becomes the email's local part, so only lowercase letters, digits and hyphens.
    resp = client.post(PATH, json={"as": name})
    assert resp.status_code == 400
    assert "token" not in resp.get_json()


def test_is_rate_limited_when_on(client):
    statuses = [client.post(PATH, json={}).status_code for _ in range(11)]
    assert statuses == [200] * 10 + [429]
