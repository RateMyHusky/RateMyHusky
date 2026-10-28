from server import professor_verify_note


def test_other_types_get_no_note():
    assert professor_verify_note("bug", "a@northeastern.edu") is None
    assert professor_verify_note("banappeal", "") is None
    # Student account deletion (Ask data, bookmarks) never touches a professor page.
    assert professor_verify_note("datadeletion", "") is None


def test_missing_email_cannot_be_verified():
    for t in ("missing", "incorrectdata", "professor"):
        assert "can't be verified" in professor_verify_note(t, "")


def test_northeastern_address_is_confirmed_by_reply():
    for email in ("J.Smith@Northeastern.edu", "j.smith@khoury.northeastern.edu"):
        assert "reply to confirm" in professor_verify_note("professor", email)


def test_other_address_is_asked_for_a_northeastern_one():
    for email in ("prof@gmail.com", "student@husky.neu.edu", "x@northeastern.edu.evil.com",
                  "x@evilnortheastern.edu"):
        assert "not a Northeastern address" in professor_verify_note("incorrectdata", email)


def test_professor_requests_require_an_email(monkeypatch):
    import server
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    resp = server.app.test_client().post(
        "/api/feedback", json={"feedbackType": "professor", "description": "remove my page"})
    assert resp.status_code == 400
    assert "Email is required" in resp.get_json()["error"]


def _post(monkeypatch, **body):
    import server
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    # Unset so a request that passes validation stops at "not configured" instead of emailing.
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setattr(server.limiter, "enabled", False)
    return server.app.test_client().post("/api/feedback", json=body)



def _post_feedback(monkeypatch, body, env=None):
    """Like _post, but with RAILWAY_ENVIRONMENT/TURNSTILE_SECRET_KEY set per test
    and the real limiter (reset) instead of a disabled one."""
    import server
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    server.limiter.reset()
    return server.app.test_client().post("/api/feedback", json=body)

def test_unknown_types_are_rejected(monkeypatch):
    resp = _post(monkeypatch, feedbackType="Buy cheap watches", description="hi")
    assert resp.status_code == 400
    assert "Unknown feedback type" in resp.get_json()["error"]


def test_every_accepted_type_passes_validation(monkeypatch):
    # Includes the merged "missing"/"feature" keys that cached bundles can still send.
    for t in ("bug", "feature", "missing", "incorrectdata", "general", "reviewreport"):
        resp = _post(monkeypatch, feedbackType=t, description="hi")
        assert resp.get_json()["error"] == "Email service not configured", t
    for t in ("banappeal", "datadeletion", "professor"):
        resp = _post(monkeypatch, feedbackType=t, description="hi", email="a@northeastern.edu",
                     accountSub=_account_token())
        assert resp.get_json()["error"] == "Email service not configured", t


def _account_token():
    import jwt
    import server
    return jwt.encode({"sub": "user-123", "iss": server.JWT_ISSUER, "aud": server.JWT_AUDIENCE},
                      server.JWT_SECRET, algorithm="HS256")


def test_data_deletion_requires_a_valid_account(monkeypatch):
    for token in (None, "not-a-jwt"):
        resp = _post(monkeypatch, feedbackType="datadeletion", description="hi",
                     email="a@northeastern.edu", accountSub=token)
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "Sign in required"


def test_invalid_requests_are_rejected_before_captcha(monkeypatch):
    import server
    monkeypatch.setattr(server.limiter, "enabled", False)
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "secret")
    def no_siteverify(*a, **kw):
        raise AssertionError("siteverify called for an invalid request")
    monkeypatch.setattr(server.http_requests, "post", no_siteverify)
    resp = server.app.test_client().post("/api/feedback", json={
        "feedbackType": "bug", "description": "x" * (server.FEEDBACK_MAX_DESCRIPTION + 1),
        "turnstileToken": "tok"})
    assert resp.status_code == 400
    assert "too long" in resp.get_json()["error"]


def test_non_string_fields_are_rejected_not_crashed(monkeypatch):
    resp = _post(monkeypatch, feedbackType=123, description="hi")
    assert resp.status_code == 400
    resp = _post(monkeypatch, feedbackType="bug", description="hi", email=None)
    assert resp.get_json()["error"] == "Email service not configured"


def test_a_non_object_body_is_a_400_not_a_500(monkeypatch):
    import server
    monkeypatch.setattr(server.limiter, "enabled", False)
    for body in ([1, 2], "text", 5):
        resp = server.app.test_client().post("/api/feedback", json=body)
        assert resp.status_code == 400, body


def test_overlong_description_is_rejected(monkeypatch):
    import server
    resp = _post(monkeypatch, feedbackType="bug", description="x" * (server.FEEDBACK_MAX_DESCRIPTION + 1))
    assert resp.status_code == 400
    assert "too long" in resp.get_json()["error"]


def test_overlong_email_is_rejected(monkeypatch):
    resp = _post(monkeypatch, feedbackType="bug", description="hi", email="a" * 250 + "@x.com")
    assert resp.status_code == 400
    assert "Invalid email" in resp.get_json()["error"]


def test_missing_turnstile_secret_fails_closed_on_railway(monkeypatch):
    resp = _post_feedback(monkeypatch, {"feedbackType": "bug", "description": "hi"},
                          env={"RAILWAY_ENVIRONMENT": "production"})
    assert resp.status_code == 503


def test_rejected_posts_do_not_use_up_the_daily_limit(monkeypatch):
    # The limit is 10 per day; only sent feedback (a 200) counts toward it.
    import server
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    server.limiter.reset()
    client = server.app.test_client()
    for _ in range(12):
        resp = client.post("/api/feedback", json={"feedbackType": "nope", "description": "hi"})
        assert resp.status_code == 400


def test_rejected_posts_still_hit_the_looser_limit(monkeypatch):
    # Junk tokens each cost a siteverify call, so a second limit counts every post.
    import server
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    server.limiter.reset()
    client = server.app.test_client()
    codes = [client.post("/api/feedback", json={"feedbackType": "nope", "description": "hi"}).status_code
             for _ in range(51)]
    assert codes[:50] == [400] * 50 and codes[50] == 429
    server.limiter.reset()


def test_turnstile_token_from_another_hostname_is_rejected(monkeypatch):
    import server

    class FakeResp:
        ok = True
        def json(self):
            return {"success": True, "hostname": "evil.example"}

    monkeypatch.setattr(server.http_requests, "post", lambda *a, **k: FakeResp())
    resp = _post_feedback(monkeypatch, {"feedbackType": "bug", "description": "hi", "turnstileToken": "t"},
                          env={"TURNSTILE_SECRET_KEY": "k", "RAILWAY_ENVIRONMENT": "production"})
    assert resp.status_code == 403


def test_turnstile_token_from_a_vercel_preview_is_accepted(monkeypatch):
    import re
    import server
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setattr(server, "PREVIEW_ORIGIN_RE", re.compile(
        r"^https://rate-my-husky-git-[a-z0-9-]+-team\.vercel\.app$"))
    preview = {"success": True, "hostname": "rate-my-husky-git-fix-1-team.vercel.app"}
    assert server._turnstile_accepts(preview)
    # Only a bare hostname counts: anything that changes the origin around it is refused.
    for hostname in ("rate-my-husky-git-fix-1-team.vercel.app.evil.example",
                     "evil.example/rate-my-husky-git-fix-1-team.vercel.app", ""):
        assert not server._turnstile_accepts({"success": True, "hostname": hostname})


def test_daily_cap_leaves_resend_free_tier_headroom(monkeypatch):
    # Resend's free tier sends 100 a day across feedback and usage alerts; stop feedback at 80.
    import server
    from datetime import datetime, timezone
    monkeypatch.setattr(server, "_feedback_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    monkeypatch.setattr(server, "_feedback_count", 79)
    assert _post(monkeypatch, feedbackType="bug", description="hi").status_code == 500  # the 80th, not configured
    resp = _post(monkeypatch, feedbackType="bug", description="hi")
    assert resp.status_code == 429 and "Daily feedback limit" in resp.get_json()["error"]


def test_signed_in_requests_get_past_a_full_anonymous_cap(monkeypatch):
    # 80 anonymous reports cost an attacker about $0.12 in CAPTCHA solves; they mustn't
    # block a data-deletion request. A ban appeal with no verified account shares the cap.
    import server
    from datetime import datetime, timezone
    monkeypatch.setattr(server, "_feedback_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    monkeypatch.setattr(server, "_feedback_count", 80)
    monkeypatch.setattr(server, "_account_feedback_count", 0, raising=False)
    monkeypatch.setattr(server, "_feedback_by_account", {})
    for t in ("datadeletion", "banappeal"):
        resp = _post(monkeypatch, feedbackType=t, description="hi", email="a@northeastern.edu",
                     accountSub=_account_token())
        assert resp.get_json()["error"] == "Email service not configured", t
    resp = _post(monkeypatch, feedbackType="banappeal", description="hi", email="a@northeastern.edu")
    assert resp.status_code == 429


def test_signed_in_allowance_has_its_own_cap(monkeypatch):
    import server
    from datetime import datetime, timezone
    monkeypatch.setattr(server, "_feedback_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    monkeypatch.setattr(server, "_feedback_count", 0)
    monkeypatch.setattr(server, "_account_feedback_count", server.ACCOUNT_FEEDBACK_DAILY_LIMIT - 1, raising=False)
    monkeypatch.setattr(server, "_feedback_by_account", {})
    body = dict(feedbackType="datadeletion", description="hi", email="a@northeastern.edu",
                accountSub=_account_token())
    assert _post(monkeypatch, **body).status_code == 500  # the last one, not configured
    resp = _post(monkeypatch, **body)
    assert resp.status_code == 429 and "Daily feedback limit" in resp.get_json()["error"]
    # Resend's free 100/day also covers up to 3 usage alerts and the daily review digest.
    assert server.FEEDBACK_DAILY_LIMIT + server.ACCOUNT_FEEDBACK_DAILY_LIMIT + 3 + 1 <= 100


def test_one_account_cannot_use_up_the_signed_in_allowance(monkeypatch):
    # One user from several IPs gets past the per-IP limiter; another user's deletion request still goes through.
    import jwt
    import server
    from datetime import datetime, timezone
    monkeypatch.setattr(server, "_feedback_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    monkeypatch.setattr(server, "_account_feedback_count", 0)
    monkeypatch.setattr(server, "_feedback_by_account", {})
    body = dict(feedbackType="banappeal", description="hi", email="a@northeastern.edu",
                accountSub=_account_token())
    for _ in range(server.FEEDBACK_PER_ACCOUNT_DAILY_LIMIT):
        assert _post(monkeypatch, **body).status_code == 500  # not configured, but counted
    assert _post(monkeypatch, **body).status_code == 429
    other = jwt.encode({"sub": "user-456", "iss": server.JWT_ISSUER, "aud": server.JWT_AUDIENCE},
                       server.JWT_SECRET, algorithm="HS256")
    resp = _post(monkeypatch, **{**body, "feedbackType": "datadeletion", "accountSub": other})
    assert resp.get_json()["error"] == "Email service not configured"


def test_json_nested_too_deep_is_400_on_every_route(monkeypatch):
    import server
    monkeypatch.setattr(server.limiter, "enabled", False)
    body = "[" * 30000 + "]" * 30000   # deep enough to recurse, small enough for MAX_CONTENT_LENGTH
    resp = server.app.test_client().post("/api/feedback", data=body, content_type="application/json")
    assert resp.status_code == 400
