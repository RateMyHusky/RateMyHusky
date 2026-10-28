import datetime
import time
import types
from urllib.parse import parse_qs, urlparse

import jwt
import server


def _client():
    return server.app.test_client()


def _start(client, query=""):
    """Start a sign-in; returns its state (as sent to Google)."""
    resp = client.get("/api/auth/google" + query)
    assert resp.status_code == 302
    state = parse_qs(urlparse(resp.headers["Location"]).query)["state"][0]
    cookies = [c for c in resp.headers.getlist("Set-Cookie") if c.startswith(server.AUTH_FLOW_COOKIE + state + "=")]
    assert cookies, "each sign-in stores a cookie named after its state"
    return state


def _fake_google(monkeypatch):
    class Resp:
        def __init__(self, body):
            self.status_code, self._body = 200, body

        def json(self):
            return self._body

    monkeypatch.setattr(server.http_requests, "post", lambda *a, **k: Resp({"access_token": "at"}))
    monkeypatch.setattr(server.http_requests, "get", lambda *a, **k: Resp(
        {"id": "u1", "email": "t@husky.neu.edu", "name": "T", "hd": "husky.neu.edu"}))


def test_callback_without_matching_state_is_refused(monkeypatch):
    monkeypatch.setattr(server.http_requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not exchange the code")))
    client = _client()
    resp = client.get("/api/auth/google/callback?code=attacker-code&state=x")
    assert "auth_error=state_mismatch" in resp.headers["Location"]
    _start(client)
    resp = client.get("/api/auth/google/callback?code=attacker-code&state=" + "a" * 43)
    assert "auth_error=state_mismatch" in resp.headers["Location"]


def test_two_tabs_signing_in_at_once_both_succeed(monkeypatch):
    _fake_google(monkeypatch)
    client = _client()
    first = _start(client, "?returnTo=/compare")
    second = _start(client, "?popup=1")
    resp = client.get(f"/api/auth/google/callback?code=c&state={first}")
    assert resp.status_code == 302 and "/compare#auth_token=" in resp.headers["Location"]
    resp = client.get(f"/api/auth/google/callback?code=c&state={second}")
    assert resp.status_code == 200 and b"auth_complete" in resp.data
    # each state works once: its cookie is deleted when used
    resp = client.get(f"/api/auth/google/callback?code=c&state={first}")
    assert "auth_error=state_mismatch" in resp.headers["Location"]


def _flow_cookies(client):
    return {c.key for c in client._cookies.values() if c.key.startswith(server.AUTH_FLOW_COOKIE)}


def test_abandoned_sign_ins_do_not_pile_up_cookies(monkeypatch):
    # Backing out of Google never reaches the callback, so each retry would add a cookie.
    server.limiter.reset()
    client = _client()
    states = []
    for i in range(6):
        # One flow per second, so their start times order them.
        monkeypatch.setattr(server, "time", types.SimpleNamespace(
            time=lambda i=i: 1_000_000 + i, perf_counter=time.perf_counter))
        states.append(_start(client))
    server.limiter.reset()
    assert _flow_cookies(client) == {server.AUTH_FLOW_COOKIE + s for s in states[-server.AUTH_FLOW_MAX:]}


def test_failed_callbacks_clear_their_flow_cookie(monkeypatch):
    server.limiter.reset()
    client = _client()
    state = _start(client)
    resp = client.get(f"/api/auth/google/callback?state={state}")   # no code: denied at Google
    assert "auth_error=no_code" in resp.headers["Location"]
    assert _flow_cookies(client) == set()
    # A malformed state from the query string never names a cookie to delete.
    resp = client.get("/api/auth/google/callback?code=c&state=bad;%20Path=/")
    assert "auth_error=state_mismatch" in resp.headers["Location"]
    assert not resp.headers.getlist("Set-Cookie")


def test_return_to_cannot_point_off_site(monkeypatch):
    _fake_google(monkeypatch)
    client = _client()
    state = _start(client, "?returnTo=//evil.example/")
    resp = client.get(f"/api/auth/google/callback?code=c&state={state}")
    assert resp.headers["Location"].startswith(server.FRONTEND_URL + "/#auth_token=")


def test_return_to_only_keeps_paths_on_this_site():
    keep = ["/", "/compare?a=1&b=2", "/professor/jane-doe", "/catalog?q=a%20b"]
    for value in keep:
        assert server._safe_return_to(value) == value
    for value in ["//evil.com", "///evil.com", "/\evil.com", "\evil.com", "https://evil.com",
                  "javascript:alert(1)", "evil.com", "", None, 5]:
        assert server._safe_return_to(value) == "/", value
    # a long URL keeps its page, losing only the query, so the cookie stays under 4KB
    assert server._safe_return_to("/catalog?q=" + "x" * 5000) == "/catalog"
    assert server._safe_return_to("/" + "x" * 5000) == "/"


def test_a_return_path_that_escapes_long_still_fits_the_cookie():
    # é is one character but six in the cookie's JSON, so the cap counts what the cookie holds.
    assert server._safe_return_to("/" + "é" * 1499) == "/"
    assert server._safe_return_to("/catalog?q=" + "é" * 1499) == "/catalog"
    for ch in ("é", '"', "\x01"):
        longest = "/" + ch * 3000
        while server._safe_return_to(longest) == "/":
            longest = longest[:-1]
        resp = _client().get("/api/auth/google", query_string={"returnTo": longest})
        cookie, = [c for c in resp.headers.getlist("Set-Cookie") if c.startswith(server.AUTH_FLOW_COOKIE)]
        assert len(cookie.split(";", 1)[0].encode()) < 4096, repr(ch)


def _token(**claims):
    base = {"sub": "u1", "email": "t@husky.neu.edu", "name": "T",
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)}
    base.update(claims)
    return jwt.encode(base, "test-secret", algorithm="HS256")


def test_session_token_needs_our_issuer_and_audience():
    assert server.decode_session_token(_token(iss=server.JWT_ISSUER, aud=server.JWT_AUDIENCE))
    assert server.decode_session_token(_token()) is None
    assert server.decode_session_token(_token(iss=server.JWT_ISSUER, aud="something-else")) is None
    assert server.decode_session_token(None) is None
    assert server.decode_session_token("not.a.jwt") is None
