import json

import server


def _report(client, body, **kw):
    return client.post("/api/csp-report", data=json.dumps(body),
                       content_type="application/csp-report", **kw)


def test_reports_are_logged_without_query_strings(capsys):
    server.limiter.reset()
    client = server.app.test_client()
    resp = _report(client, {"csp-report": {
        "document-uri": "https://ratemyhusky.com/search?q=secret#x",
        "violated-directive": "script-src",
        "blocked-uri": "https://evil.example/x.js?t=1",
    }}, headers={"Origin": "null"})
    assert resp.status_code == 204
    line = [l for l in capsys.readouterr().out.splitlines() if l.startswith("[csp] ")][-1]
    logged = json.loads(line[len("[csp] "):])
    assert logged["document-uri"] == "https://ratemyhusky.com/search"
    assert logged["blocked-uri"] == "https://evil.example/x.js"
    assert logged["violated-directive"] == "script-src"


def test_junk_bodies_are_a_204_and_log_nothing(capsys):
    server.limiter.reset()
    client = server.app.test_client()
    for body in ([1], "x", {"csp-report": "x"}, {}):
        assert _report(client, body).status_code == 204
    assert "[csp] " not in capsys.readouterr().out
