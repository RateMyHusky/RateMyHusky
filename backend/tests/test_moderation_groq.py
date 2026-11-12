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
    assert mg.check("Fair exams.", groq) == ("allow", None, 500)
    (call,) = groq.calls
    assert call["model"] == mg.MODEL and call["temperature"] == 0 and call["reasoning_effort"] == mg.EFFORT == "low"
    assert call["messages"] == [{"role": "system", "content": mg.POLICY},
                                {"role": "user", "content": "Fair exams."}]


def test_check_answers_and_failures(fake_groq):
    assert mg.check("x", fake_groq("REVIEW")) == ("review", "review", 500)
    assert mg.check("x", fake_groq("BLOCK")) == ("block", "blocked", 500)
    assert mg.check("x", fake_groq("??")) == ("review", "review", 500)
    assert mg.check("x", fake_groq(fake_groq.RateLimited("429"))) == ("unavailable", "groq_rate_limited", None)
    assert mg.check("x", fake_groq(TimeoutError("3 s"))) == ("unavailable", "groq_unavailable", None)
    assert mg.check("x", fake_groq(RuntimeError("500"))) == ("unavailable", "groq_unavailable", None)


def test_check_without_usage_records_no_tokens():
    message = type("Message", (), {"content": "ALLOW"})()
    resp = type("Response", (), {"choices": [type("Choice", (), {"message": message})()]})()
    groq = type("Groq", (), {})()
    groq.chat = type("Chat", (), {})()
    groq.chat.completions = type("Completions", (), {"create": lambda self, **kw: resp})()
    assert mg.check("x", groq) == ("allow", None, None)


def test_the_policy_blocks_attacks_on_appearance():
    assert "Attacks on appearance, body, weight, or private life" in mg.POLICY


def test_the_policy_sends_any_doubtful_part_to_review():
    assert "ALLOW is only for reviews whose every part fits the ALLOW list." in mg.POLICY
    assert "never ALLOW such a review" in mg.POLICY


def test_enabled_follows_the_key(monkeypatch):
    assert mg.enabled() is False  # conftest sets it empty
    monkeypatch.setenv("groq1", "  ")
    assert mg.enabled() is False
    monkeypatch.setenv("groq1", "gsk-test")
    assert mg.enabled() is True


def test_the_client_fails_fast_with_no_retries(monkeypatch):
    monkeypatch.setenv("groq1", "gsk-test")
    groq = mg.client()  # builds only, no request
    assert str(groq.base_url).rstrip("/") == mg.BASE_URL
    assert groq.max_retries == 0 and groq.timeout == mg.TIMEOUT
