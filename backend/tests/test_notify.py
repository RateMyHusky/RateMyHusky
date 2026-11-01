import notify
import pytest
import requests


class _Resp:
    def __init__(self, status=200, body=None, bad_json=False):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._body


def _capture_post(monkeypatch):
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent["url"] = url
        sent["payload"] = json
        return _Resp(200)

    monkeypatch.setattr(notify.http_requests, "post", fake_post)
    return sent


def test_send_defaults_to_the_team_inbox_with_text_only(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    sent = _capture_post(monkeypatch)
    assert notify.send_team_email("s", "t") is True
    assert sent["payload"]["to"] == ["feedback@ratemyhusky.com"]
    assert "html" not in sent["payload"]
    assert sent["payload"]["from"] == "RateMyHusky <feedback@ratemyhusky.com>"


def test_send_to_another_inbox_with_html(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    sent = _capture_post(monkeypatch)
    assert notify.send_team_email("s", "t", to=notify.DIGEST_EMAIL, html="<p>x</p>") is True
    assert sent["payload"]["to"] == ["ratings@ratemyhusky.com"]
    assert sent["payload"]["html"] == "<p>x</p>"
    assert sent["payload"]["text"] == "t"
    assert sent["payload"]["from"] == "RateMyHusky <feedback@ratemyhusky.com>"


def test_resend_usage_reads_daily_and_monthly(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        return _Resp(200, {"object": "usage", "emails": {
            "daily": {"used": 10, "limit": 100, "sent": 8, "received": 2},
            "monthly": {"used": 1212, "limit": 3000}}})

    monkeypatch.setattr(notify.http_requests, "get", fake_get)
    assert notify.resend_usage() == {"daily": {"used": 10, "limit": 100},
                                     "monthly": {"used": 1212, "limit": 3000}}
    assert seen["url"] == "https://api.resend.com/usage"
    assert seen["headers"]["Authorization"] == "Bearer re_test"


@pytest.mark.parametrize("status", [401, 403])
def test_resend_usage_is_none_for_a_sending_only_key(monkeypatch, status):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setattr(notify.http_requests, "get", lambda *a, **k: _Resp(status, {}))
    assert notify.resend_usage() is None


def test_resend_usage_is_none_on_errors(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")

    def boom(*a, **k):
        raise requests.Timeout()

    monkeypatch.setattr(notify.http_requests, "get", boom)
    assert notify.resend_usage() is None
    monkeypatch.setattr(notify.http_requests, "get", lambda *a, **k: _Resp(200, bad_json=True))
    assert notify.resend_usage() is None
    monkeypatch.setattr(notify.http_requests, "get", lambda *a, **k: _Resp(200, {}))
    assert notify.resend_usage() is None

    calls = []
    monkeypatch.setattr(notify.http_requests, "get", lambda *a, **k: calls.append(1))
    monkeypatch.delenv("RESEND_API_KEY")
    assert notify.resend_usage() is None
    assert calls == []


def test_resend_usage_keeps_a_null_limit(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setattr(notify.http_requests, "get", lambda *a, **k: _Resp(200, {"emails": {
        "daily": {"used": 10, "limit": None}, "monthly": {"used": 1212, "limit": 3000}}}))
    assert notify.resend_usage()["daily"] == {"used": 10, "limit": None}
