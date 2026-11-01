import pytest

import usage_alert


@pytest.mark.parametrize("sent", [True, False])
def test_an_alert_email_is_counted_only_when_resend_accepts_it(monkeypatch, sent):
    monkeypatch.setattr(usage_alert, "daily_budget", lambda keys: 100)
    monkeypatch.setattr(usage_alert, "_today_ok_count", lambda q1: 60)
    monkeypatch.setattr(usage_alert, "build_summary", lambda *a: {})
    monkeypatch.setattr(usage_alert, "render_email", lambda tier, summary: ("s", "t"))
    writes = []

    def write(sql, params=None):
        writes.append(sql)
        return 1

    assert usage_alert.maybe_alert(None, None, write, 1, send_fn=lambda payload: sent) == [50]
    assert writes[1:] == (["INSERT INTO email_sends DEFAULT VALUES"] if sent else [])
