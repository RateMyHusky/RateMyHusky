"""Unit tests for the pure rating decision functions in rating_checks.py."""

import pytest

import rating_checks as rc


def test_assess_accepts_a_clean_rating():
    assert rc.assess(30, "campus", [], False) == ("accepted", [])


def test_hold_reasons_in_order():
    assert rc.assess(3, "datacenter", ["burst_pair"], True) == (
        "held", ["too_fast", "datacenter", "burst_pair", "duplicate_comment"])
    assert rc.assess(None, "other", [], False) == ("held", ["no_timer"])
    assert rc.assess(7201, "relay", [], False) == ("held", ["stale"])


def test_quick_edit_of_an_accepted_rating_is_not_too_fast():
    assert rc.assess(3, "campus", [], False, edit=True) == ("accepted", [])
    assert rc.assess(2, "campus", [], False, edit=True) == ("held", ["too_fast"])


def test_an_edit_still_needs_a_timer():
    assert rc.assess(None, "campus", [], False, edit=True) == ("held", ["no_timer"])


def test_campus_relay_mobile_unknown_never_hold_on_their_own():
    for n in ("campus", "relay", "mobile", "other", "unknown"):
        assert rc.assess(30, n, [], False)[0] == "accepted"


def test_moderation_failure_is_unavailable():
    def boom(texts): raise RuntimeError("timeout")
    assert rc.moderate("fine comment", score=boom) == "unavailable"
    assert rc.moderate("   ", score=boom) is None


def test_moderate_returns_the_action():
    class V:
        action = "review"
    assert rc.moderate("fine comment", score=lambda texts: [V()]) == "review"


def test_comment_hash_ignores_case_and_punctuation_and_skips_short():
    assert rc.comment_hash("Great prof!!  Lectures were CLEAR.") == rc.comment_hash("great prof lectures were clear")
    assert rc.comment_hash("great prof") is None


def _body(**over):
    body = {"professor": {"slug": "jane-doe"}, "course": {"code": "CS2500"}, "term": "Fall 2025",
            "rating": 4, "difficulty": 3, "hours": "3-4", "grade": "A", "comment": "ok"}
    body.update(over)
    return body


@pytest.mark.parametrize("body", [
    _body(professor={"slug": "jane-doe", "name": "Jane Doe"}),
    _body(professor={}),
    _body(professor={"name": "Cher"}),
    _body(course={"code": "CS 25"}),
    _body(rating=True),
    _body(rating=4.5),
    _body(rating=6),
    _body(hours="15+"),
    _body(difficulty=0),
    _body(difficulty=6),
    _body(difficulty=2.5),
    _body(difficulty=True),
    _body(grade="D"),
    _body(term="Fall 2015"),
    _body(term="Fall 2021"),
    _body(term="Autumn 2025"),
    _body(term="Summer Full 2025"),
    _body(term="Fall 2025\n"),
    _body(term="Fall ٢٠٢٥"),
    _body(course={"code": "CS２５００"}),
    _body(comment="x" * 2001),
    _body(professor="jane-doe"),
    _body(course=None),
    _body(professor={"slug": 5}),
    _body(professor={"name": "Jane Doe", "department": "x" * 101}),
    _body(course={"code": "CS2500", "name": "ab"}),
])
def test_validate_rejects(body):
    clean, err = rc.validate_submission(body, 2026)
    assert clean is None and err


@pytest.mark.parametrize("bad", ["a" + chr(0) + "b", "a" + chr(0xD800) + "b"], ids=["nul", "lone-surrogate"])
@pytest.mark.parametrize("make", [
    lambda bad: _body(professor={"slug": bad}),
    lambda bad: _body(professor={"name": bad + " Smith"}),
    lambda bad: _body(professor={"name": "Jane Doe", "department": bad}),
    lambda bad: _body(course={"code": "CS2500", "name": bad + "abc"}),
    lambda bad: _body(comment=bad),
    lambda bad: _body(term=bad),
    lambda bad: _body(hours=bad),
    lambda bad: _body(grade=bad),
])
def test_validate_rejects_text_postgres_cannot_store(make, bad):
    clean, err = rc.validate_submission(make(bad), 2026)
    assert clean is None and "can't be stored" in err


@pytest.mark.parametrize("body", [None, [], "x", 5, [1, 2], {}, {"professor": [], "course": 3},
                                  _body(comment=7), _body(term=5), _body(hours=None), _body(grade=3)])
def test_validate_never_raises(body):
    clean, err = rc.validate_submission(body, 2026)
    assert clean is None and err


def test_validate_cleans():
    clean, err = rc.validate_submission(
        {"professor": {"slug": "jane-doe"}, "course": {"code": "cs 2500"}, "term": "Summer 2025",
         "rating": 4, "difficulty": 2, "hours": "3-4", "grade": None, "comment": "  ok  "}, 2026)
    assert err is None
    assert clean["professor_slug"] == "jane-doe" and clean["new_professor"] is None
    assert clean["course_code"] == "CS2500" and clean["new_course_name"] is None
    assert clean["term_label"] == "Summer 2025"
    assert clean["rating"] == 4 and clean["hours"] == "3-4" and clean["grade"] is None
    assert clean["difficulty"] == 2
    assert clean["comment"] == "ok"


def test_validate_accepts_a_missing_difficulty():
    # A page still running the form from before the question sends none.
    body = _body()
    del body["difficulty"]
    clean, err = rc.validate_submission(body, 2026)
    assert err is None and clean["difficulty"] is None


def test_new_professor_name_needs_two_latin_words():
    # These would key to "" or one word and share a pending row with other names.
    for name in ("李 明", "李 Ming", "-- --"):
        clean, err = rc.validate_submission(_body(professor={"name": name}), 2026)
        assert clean is None and "Latin letters" in err
    for name in ("Ana Muñoz", "Mary-Kate Olsen", "J. Smith"):
        assert rc.validate_submission(_body(professor={"name": name}), 2026)[1] is None


def test_validate_new_professor_and_course():
    clean, err = rc.validate_submission(
        _body(professor={"name": " Jane  Doe ", "department": ""}, course={"code": "cs2500", "name": "Fundies"},
              term=None, comment=None), 2026)
    assert err is None
    assert clean["professor_slug"] is None
    assert clean["new_professor"] == {"name": "Jane Doe", "department": None}
    assert clean["new_course_name"] == "Fundies" and clean["term_label"] is None and clean["comment"] == ""


def test_validate_missing_grade_is_none():
    body = _body()
    del body["grade"]
    clean, err = rc.validate_submission(body, 2026)
    assert err is None and clean["grade"] is None


def test_validate_accepts_banner_labels():
    for term in ("Winter 2026", "Summer 1 2025", "Fall 2025"):
        clean, err = rc.validate_submission(_body(term=term), 2026)
        assert err is None and clean["term_label"] == term


def test_validate_term_window_is_four_years_plus_a_year_each_side():
    # The form's four years, plus one each side for a browser whose year differs from UTC's.
    for term in ("Fall 2022", "Fall 2023", "Spring 2026", "Fall 2027"):
        assert rc.validate_submission(_body(term=term), 2026)[1] is None
    for term in ("Summer 2 2021", "Spring 2028"):
        assert rc.validate_submission(_body(term=term), 2026)[1] == "Invalid term"


def test_a_pair_banner_and_rmp_never_saw_is_held_for_review():
    assert rc.assess(30, "campus", [], False, unverified_pair=True) == ("held", ["unverified_pair"])
    assert rc.assess(30, "other", ["burst_prof"], True, unverified_pair=True) == (
        "held", ["burst_prof", "unverified_pair", "duplicate_comment"])


@pytest.mark.parametrize("comment,reason", [
    ("great class, notes at https://example.org/notes", "link"),
    ("check www.studyhelp.net for answers", "link"),
    ("answers on cheapessays.com lol", "link"),
    ("dm me on cheapessays dot com", "link"),
    ("cheapessays(dot)com", "link"),
    ("join t.me/answers for the keys", "link"),
    ("use code SAVE20 at checkout", "promo"),
    ("promo code: HUSKY for 20% off tutoring", "promo"),
    ("text me 617-555-0123 for notes", "phone"),
    ("call (617) 555 0123", "phone"),
    ("+1 617.555.0123", "phone"),
    ("email me at jane.doe@gmail.com", "email"),
    ("reach me: jane.doe [at] gmail", "email"),
    ("she lives at 360 Huntington Ave near campus", "address"),
    ("asdfasdf", "mash"),
    ("jfkdlsjfkdlsjfk", "mash"),
    ("hhhhhhhhhhhhhhhhhhhh bad prof qwrtpsdfg", "mash"),
])
def test_rules_block_links_contact_details_and_mashing(comment, reason):
    assert rc.rule_block(comment) == reason


@pytest.mark.parametrize("comment", [
    "ok", "n/a", ".", "none", "idk", "lol", "tbh mid", "10/10",
    "She takes 10% off for every absence.",
    "Tests are 40% of the grade, the final is 2-3 hours.",
    "Class meets 9:50-11:30 in Snell 108, room changed twice.",
    "Professor Wertheim is great.", "Uses ASP.NET and Node.js.",
    "soooooo boringgggggg, RUNNNNNNNN", "read the pwrpnts and asgnmts before tests",
    "the e.g. examples in the textbook (ch. 3.2) helped",
    "Office hours in 177 Huntington were useful",
    "the TA's email is on Canvas",
    "CS2500 then CS2510, take it with him",
])
def test_ordinary_reviews_pass_the_rules(comment):
    assert rc.rule_block(comment) is None


def test_check_fields_for_each_outcome():
    now = "NOW"
    assert rc.comment_check_fields("allow", None, now) == {
        "comment_check": "allow", "comment_check_reason": None, "comment_check_attempts": 1,
        "comment_next_check_at": None, "comment_checked_at": now}
    assert rc.comment_check_fields("review", "review", now)["comment_check"] == "review"
    failed = rc.comment_check_fields("unavailable", "groq_rate_limited", now)
    assert failed == {"comment_check": "unchecked", "comment_check_reason": "groq_rate_limited",
                      "comment_check_attempts": 1, "comment_next_check_at": now, "comment_checked_at": None}
    over = rc.comment_check_fields("over_budget", None, now)
    assert (over["comment_check_reason"], over["comment_check_attempts"], over["comment_next_check_at"]) == (
        "over_budget", 0, now)
    # A flood's comments are never queued, or it would spend the queue's calls instead.
    for skipped in ("duplicate", "burst"):
        fields = rc.comment_check_fields(skipped, None, now)
        assert fields["comment_check"] == "unchecked" and fields["comment_check_reason"] == skipped
        assert fields["comment_next_check_at"] is None and fields["comment_check_attempts"] == 0
