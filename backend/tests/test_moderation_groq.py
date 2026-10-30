"""moderation_groq.py against the FakeGroq in conftest: no test reaches Groq."""

import moderation_groq as mg


def test_the_first_label_found_wins_in_block_review_allow_order():
    assert mg.parse("ALLOW") == "allow"
    assert mg.parse("  review\n") == "review"
    assert mg.parse("BLOCK") == "block"
    assert mg.parse("ALLOW... actually BLOCK") == "block"
    assert mg.parse("REVIEW or ALLOW") == "review"


def test_any_other_reply_is_review():
    for reply in ("", None, "I can't decide", "OK"):
        assert mg.parse(reply) == "review"


def test_check_sends_the_policy_and_the_comment(fake_groq):
    groq = fake_groq("ALLOW")
    assert mg.check("Fair exams.", groq) == ("allow", None)
    (call,) = groq.calls
    assert call["model"] == mg.MODEL and call["temperature"] == 0 and call["reasoning_effort"] == "low"
    assert call["messages"] == [{"role": "system", "content": mg.POLICY},
                                {"role": "user", "content": "Fair exams."}]


def test_check_answers_and_failures(fake_groq):
    assert mg.check("x", fake_groq("REVIEW")) == ("review", "review")
    assert mg.check("x", fake_groq("BLOCK")) == ("block", "blocked")
    assert mg.check("x", fake_groq("??")) == ("review", "review")
    assert mg.check("x", fake_groq(fake_groq.RateLimited("429"))) == ("unavailable", "groq_rate_limited")
    assert mg.check("x", fake_groq(TimeoutError("3 s"))) == ("unavailable", "groq_unavailable")
    assert mg.check("x", fake_groq(RuntimeError("500"))) == ("unavailable", "groq_unavailable")


def test_the_policy_blocks_attacks_on_appearance():
    assert "Attacks on appearance, body, weight, or private life" in mg.POLICY


def test_enabled_follows_the_key(monkeypatch):
    assert mg.enabled() is False  # conftest sets it empty
    monkeypatch.setenv("GROQ_MODERATION_KEY", "  ")
    assert mg.enabled() is False
    monkeypatch.setenv("GROQ_MODERATION_KEY", "gsk-test")
    assert mg.enabled() is True


def test_the_client_fails_fast_with_no_retries(monkeypatch):
    monkeypatch.setenv("GROQ_MODERATION_KEY", "gsk-test")
    groq = mg.client()  # builds only, no request
    assert str(groq.base_url).rstrip("/") == mg.BASE_URL
    assert groq.max_retries == 0 and groq.timeout == mg.TIMEOUT
