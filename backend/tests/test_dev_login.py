"""The local-dev sign-in (/api/auth/dev-login): off unless DEV_LOGIN=1 and not on
Railway, and when on it issues the same kind of session token Google sign-in does."""
import time
from urllib.parse import urlparse

import pytest
import server


@pytest.fixture
def client(monkeypatch):
    server.limiter.reset()
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.setenv("DEV_LOGIN", "1")
    return server.app.test_client()


def _token(resp):
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert "#auth_token=" in location
    return location, location.split("#auth_token=", 1)[1]


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes"])
def test_off_without_the_opt_in(client, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("DEV_LOGIN", raising=False)
    else:
        monkeypatch.setenv("DEV_LOGIN", value)
    resp = client.get("/api/auth/dev-login")
    assert resp.status_code == 404
    assert "auth_token" not in resp.headers.get("Location", "")


@pytest.mark.parametrize("env", ["production", "dev"])
def test_off_on_railway_even_with_the_opt_in(client, monkeypatch, env):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", env)
    resp = client.get("/api/auth/dev-login")
    assert resp.status_code == 404
    assert "auth_token" not in resp.headers.get("Location", "")


def test_issues_a_session_the_backend_accepts(client):
    location, token = _token(client.get("/api/auth/dev-login?returnTo=/compare?a=1"))
    assert location.startswith(f"{server.FRONTEND_URL}/compare?a=1#auth_token=")
    claims = server.decode_session_token(token)
    assert claims["sub"] == "dev-login:dev"
    assert claims["email"] == "dev@husky.neu.edu"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.get_json() == {"email": "dev@husky.neu.edu", "name": "Dev User", "picture": ""}


def test_token_expires_like_a_google_session(client):
    _, token = _token(client.get("/api/auth/dev-login"))
    claims = server.decode_session_token(token)
    remaining = claims["exp"] - time.time()
    assert server.SESSION_DAYS * 86400 - 60 < remaining <= server.SESSION_DAYS * 86400


def test_as_picks_a_separate_account(client):
    _, ben = _token(client.get("/api/auth/dev-login?as=ben"))
    _, dev = _token(client.get("/api/auth/dev-login"))
    ben_claims, dev_claims = server.decode_session_token(ben), server.decode_session_token(dev)
    assert ben_claims["sub"] == "dev-login:ben" and ben_claims["email"] == "ben@husky.neu.edu"
    assert ben_claims["name"] == "Dev ben"
    assert ben_claims["sub"] != dev_claims["sub"]


@pytest.mark.parametrize("name", ["Ben", "a b", "x" * 33, "-x", "../x", "ben@evil.com", ""])
def test_as_refuses_names_outside_the_allowed_shape(client, name):
    # The name becomes the email's local part, so only lowercase letters, digits and hyphens.
    resp = client.get("/api/auth/dev-login", query_string={"as": name})
    assert resp.status_code == 400


@pytest.mark.parametrize("return_to", ["https://evil.com", "//evil.com", "/\\evil.com", "compare"])
def test_return_to_stays_on_the_site(client, return_to):
    location, _ = _token(client.get("/api/auth/dev-login", query_string={"returnTo": return_to}))
    assert urlparse(location).netloc == urlparse(server.FRONTEND_URL).netloc
    assert location.startswith(f"{server.FRONTEND_URL}/#auth_token=")
