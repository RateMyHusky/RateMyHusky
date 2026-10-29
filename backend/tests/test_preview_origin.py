"""PREVIEW_ORIGIN_RE: Vercel Preview origins pass the origin check and keep login on the preview."""

import re

import pytest

PREVIEW = "https://rate-my-husky-abc123-grain-is-grainys-projects.vercel.app"
PATTERN = r"^https://rate-my-husky-(?:git-[a-z0-9-]+|[a-z0-9]+)-grain-is-grainys-projects\.vercel\.app$"


@pytest.fixture
def server_mod(monkeypatch):
    import server
    monkeypatch.setattr(server, "_get_pool", lambda: (_ for _ in ()).throw(AssertionError("no DB in test")), raising=False)
    monkeypatch.setattr(server, "FRONTEND_URL", "https://ratemyhusky.com")
    monkeypatch.setattr(server, "PREVIEW_ORIGIN_RE", re.compile(PATTERN))
    return server


@pytest.mark.parametrize("referer", [
    PREVIEW + "/professors",
    "https://rate-my-husky-git-preview-gate-grain-is-grainys-projects.vercel.app/",
    "http://localhost:5173/",
])
def test_allowed_origins_pass(server_mod, referer):
    with server_mod.app.test_request_context("/api/professors", headers={"Referer": referer}):
        assert server_mod.check_origin() is None


@pytest.mark.parametrize("referer", [
    "https://rate-my-husky-abc123-someone-else.vercel.app/",
    # Hash URL under another team whose slug ends in "-grain-is-grainys-projects"
    # (its git-<branch> alias still matches; see the server.py comment)
    "https://rate-my-husky-abc123-x-grain-is-grainys-projects.vercel.app/",
    "https://evil.example/" + PREVIEW,
    PREVIEW + ".evil.example/",
    "http://rate-my-husky-abc123-grain-is-grainys-projects.vercel.app/",
])
def test_lookalike_origins_blocked(server_mod, referer):
    with server_mod.app.test_request_context("/api/professors", headers={"Referer": referer}):
        resp = server_mod.check_origin()
        assert resp is not None and resp[1] == 403


def test_unset_pattern_blocks_previews(server_mod, monkeypatch):
    monkeypatch.setattr(server_mod, "PREVIEW_ORIGIN_RE", None)
    with server_mod.app.test_request_context("/api/professors", headers={"Referer": PREVIEW + "/"}):
        resp = server_mod.check_origin()
        assert resp is not None and resp[1] == 403


def _flow_cookie(server_mod, resp):
    """The Set-Cookie header of the sign-in's own auth_flow_<state> cookie."""
    cookies = [c for c in resp.headers.getlist("Set-Cookie") if c.startswith(server_mod.AUTH_FLOW_COOKIE)]
    assert len(cookies) == 1
    return cookies[0]


def test_login_from_preview_uses_preview_redirect(server_mod):
    client = server_mod.app.test_client()
    resp = client.get("/api/auth/google?popup=1", headers={"Referer": PREVIEW + "/courses"})
    assert resp.status_code == 302
    assert "redirect_uri=" + "https%3A%2F%2Frate-my-husky-abc123" in resp.headers["Location"]
    assert PREVIEW in _flow_cookie(server_mod, resp)


def test_login_from_prod_unchanged(server_mod):
    client = server_mod.app.test_client()
    resp = client.get("/api/auth/google?popup=1", headers={"Referer": "https://ratemyhusky.com/"})
    assert "redirect_uri=https%3A%2F%2Fratemyhusky.com%2Fapi" in resp.headers["Location"]
    assert "origin" not in _flow_cookie(server_mod, resp)


@pytest.mark.parametrize("flow,expected", [
    ({"origin": PREVIEW}, PREVIEW),
    ({"origin": "https://evil.example"}, "https://ratemyhusky.com"),
    ({"origin": ["x"]}, "https://ratemyhusky.com"),
    ({}, "https://ratemyhusky.com"),
    (None, "https://ratemyhusky.com"),
])
def test_callback_rechecks_cookie(server_mod, flow, expected):
    # The sign-in's own cookie is client-held, so its origin is re-checked.
    assert server_mod._callback_frontend(flow) == expected


def test_preview_sign_in_returns_to_the_preview(server_mod, monkeypatch):
    from urllib.parse import parse_qs, urlparse

    class Resp:
        def __init__(self, body):
            self.status_code, self._body = 200, body

        def json(self):
            return self._body

    monkeypatch.setattr(server_mod.http_requests, "post", lambda *a, **k: Resp({"access_token": "at"}))
    monkeypatch.setattr(server_mod.http_requests, "get", lambda *a, **k: Resp(
        {"id": "u1", "email": "t@husky.neu.edu", "name": "T", "hd": "husky.neu.edu"}))
    client = server_mod.app.test_client()
    resp = client.get("/api/auth/google?returnTo=/courses", headers={"Referer": PREVIEW + "/courses"})
    state = parse_qs(urlparse(resp.headers["Location"]).query)["state"][0]
    resp = client.get(f"/api/auth/google/callback?code=c&state={state}")
    assert resp.headers["Location"].startswith(PREVIEW + "/courses#auth_token=")
