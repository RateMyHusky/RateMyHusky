import notify


class _Resp:
    def __init__(self, status=200):
        self.status_code = status
        self.ok = 200 <= status < 300


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

