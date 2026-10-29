"""get_real_ip: X-RMH-Client-IP is trusted only when PROXY_SECRET is set."""

import os

import pytest

HEADERS = {"X-Proxy-Key": "s3cret", "X-RMH-Client-IP": "203.0.113.9", "X-Forwarded-For": "1.1.1.1, 198.51.100.7"}


@pytest.fixture
def server_mod(monkeypatch):
    os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
    os.environ.setdefault("JWT_SECRET", "test-secret")
    import server
    monkeypatch.setattr(server, "_get_pool", lambda: (_ for _ in ()).throw(AssertionError("no DB in test")), raising=False)
    return server


def test_header_trusted_with_secret(server_mod, monkeypatch):
    monkeypatch.setattr(server_mod, "PROXY_SECRET", "s3cret")
    with server_mod.app.test_request_context(headers=HEADERS):
        assert server_mod.get_real_ip() == "203.0.113.9"


def test_header_ignored_without_secret(server_mod, monkeypatch):
    monkeypatch.setattr(server_mod, "PROXY_SECRET", None)
    with server_mod.app.test_request_context(headers=HEADERS):
        assert server_mod.get_real_ip() == "198.51.100.7"


def test_falls_back_when_header_absent(server_mod, monkeypatch):
    monkeypatch.setattr(server_mod, "PROXY_SECRET", "s3cret")
    with server_mod.app.test_request_context(headers={"X-Proxy-Key": "s3cret", "X-Forwarded-For": "1.1.1.1, 198.51.100.7"}):
        assert server_mod.get_real_ip() == "198.51.100.7"


def test_blank_header_treated_as_absent(server_mod, monkeypatch):
    monkeypatch.setattr(server_mod, "PROXY_SECRET", "s3cret")
    with server_mod.app.test_request_context(headers={"X-Proxy-Key": "s3cret", "X-RMH-Client-IP": "  ", "X-Forwarded-For": "1.1.1.1, 198.51.100.7"}):
        assert server_mod.get_real_ip() == "198.51.100.7"


@pytest.mark.parametrize("key", [None, "wrong", "ÿ"])
def test_header_ignored_without_valid_key(server_mod, monkeypatch, key):
    monkeypatch.setattr(server_mod, "PROXY_SECRET", "s3cret")
    headers = {k: v for k, v in HEADERS.items() if k != "X-Proxy-Key"}
    if key:
        headers["X-Proxy-Key"] = key
    with server_mod.app.test_request_context(headers=headers):
        assert server_mod.get_real_ip() == "198.51.100.7"


def test_non_ascii_proxy_key_is_a_403_not_a_500(server_mod, monkeypatch):
    # WSGI decodes headers as latin-1, and compare_digest raises on non-ASCII str.
    monkeypatch.setattr(server_mod, "PROXY_SECRET", "s3cret")
    resp = server_mod.app.test_client().get("/api/stats", headers={"X-Proxy-Key": "ÿ"})
    assert resp.status_code == 403
