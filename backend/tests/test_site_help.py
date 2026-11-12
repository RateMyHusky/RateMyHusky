import pytest
from rag import site_help
from rag.chat_gate import MAX_QUERY_LEN

IDS = ["menu", "data_sources", "affiliation", "rate", "goated", "compare", "sentiment",
       "photos", "no_ratings", "missing_course", "offerings", "awards", "report", "search",
       "bookmarks", "departments", "sign_in", "theme", "professors", "privacy", "ask_help",
       "courses"]

# One question per topic that must offer that topic (other topics may be offered too).
OFFERS = {
    "data_sources": ["where do the ratings come from", "is the reddit data recent"],
    "affiliation": ["is this site official", "who runs RateMyHusky"],
    "rate": ["how do I rate a professor", "where is the rating form"],
    "goated": ["who is the best CS professor", "how is the GOATED list ranked"],
    "compare": ["Guha vs Lieberherr", "how do I compare professors"],
    "sentiment": ["what does the sentiment bar mean"],
    "photos": ["why is there no photo", "where do the headshots come from"],
    "no_ratings": ["why does this page have no ratings", "a professor with zero reviews"],
    "missing_course": ["a course is missing from the page", "my class is not listed"],
    "offerings": ["what does last taught mean", "when is CS3500 offered"],
    "awards": ["what do the award badges mean", "is there a badge for teaching"],
    "report": ["how do I report a bug", "this rating is wrong"],
    "search": ["where is the search bar", "how do I look up a course"],
    "bookmarks": ["how do bookmarks work", "where are my saved courses"],
    "departments": ["is there a departments page"],
    "sign_in": ["how do I sign in", "do I need a login", "sign-in isn't working"],
    "theme": ["how do I turn on dark mode", "can I change the theme"],
    "professors": ["I teach at Northeastern", "how do I take down my page"],
    "privacy": ["what is your privacy policy", "where are the terms of service"],
    "ask_help": ["what can I ask", "what can you answer"],
    "courses": ["help me plan my semester", "can I filter courses by rating", "how do I sort courses"],
}

# Questions with no topic keyword go straight to the LLM.
NO_TOPIC = [
    "is Guha a good teacher", "is CS3500 hard", "who teaches DS 3000",
    "how do I get an A in CS2500", "tell me about Lieberherr", "is algorithms worth taking",
    # Whole words only: these contain a keyword as part of a longer word.
    "is the workload heavy in topology", "who is the vsauce of khoury", "what about pratesi",
]

MENU = ["help", "menu", "hi", "Hey!", "what can you do", "Hi, what can you do?",
        "what is this site", "what is RateMyHusky?", "can you help me", "i need help"]


def _ids(q):
    return [h.entry.id for h in site_help.matches(q)]


def test_registry_has_every_entry():
    assert sorted(e.id for e in site_help.ENTRIES) == sorted(IDS)   # each id exactly once
    assert site_help.ENTRIES[-1].id == "menu"


def test_every_topic_has_keywords_and_a_test():
    topics = [e for e in site_help.ENTRIES if e.id != "menu"]
    assert all(e.keywords for e in topics)
    assert set(OFFERS) == {e.id for e in topics}


def test_menu_has_no_keywords():
    assert site_help.get("menu").keywords == ()


@pytest.mark.parametrize("entry_id,q", [(k, q) for k, qs in OFFERS.items() for q in qs])
def test_question_offers_its_topic(entry_id, q):
    assert entry_id in _ids(q)


@pytest.mark.parametrize("q", NO_TOPIC)
def test_question_without_keyword_offers_nothing(q):
    assert site_help.matches(q) == []


def test_professor_questions_still_offer_topics():
    # The prompt's "No, other" button sends these to the LLM, so naming someone doesn't skip it.
    assert "compare" in _ids("compare Guha vs Lieberherr for CS3500")
    assert "goated" in _ids("is professor Lee the best")


def test_hit_records_the_keyword_that_fired():
    hit = next(h for h in site_help.matches("Guha VS Lieberherr") if h.entry.id == "compare")
    assert hit.keyword == "vs"


def test_keyword_matches_simple_plural():
    assert "bookmarks" in _ids("where are my bookmarks")
    assert "data_sources" in _ids("where do ratings come from")


def test_curly_apostrophes_match():
    assert "missing_course" in _ids("my class isn’t listed")


def test_matches_follow_registry_order_and_are_capped():
    q = "compare the best ratings, report a bug, bookmark, dark mode, privacy"
    ids = _ids(q)
    order = [e.id for e in site_help.ENTRIES]
    assert ids == sorted(ids, key=order.index)
    assert len(ids) == site_help.MAX_CHOICES


def test_each_topic_offered_once():
    ids = _ids("compare compare vs versus")
    assert ids == ["compare"]


@pytest.mark.parametrize("q", MENU)
def test_menu_request(q):
    assert site_help.is_menu_request(q)


@pytest.mark.parametrize("q", ["help me plan my semester", "is Guha helpful", "hi is Guha good"])
def test_not_a_menu_request(q):
    assert not site_help.is_menu_request(q)


def test_overlong_text_matches_nothing():
    q = "how do bookmarks work " + "x" * MAX_QUERY_LEN
    assert site_help.matches(q) == [] and not site_help.is_menu_request(q)


def test_empty_text_matches_nothing():
    assert site_help.matches("") == [] and site_help.matches("?!") == []


def test_choice_payload_shape():
    hits = site_help.matches("Guha vs Lieberherr, who is best")
    p = site_help.choice_payload(hits)
    assert p["mode"] == "site_help_choice"
    assert p["message"] == "Is your question about one of these?"
    assert p["options"] == [{"id": h.entry.id, "title": h.entry.title} for h in hits]


def test_hit_summary_names_topic_and_keyword():
    hits = site_help.matches("Guha vs Lieberherr, who is best")
    assert site_help.hit_summary(hits) == "goated:best compare:vs"


def test_answers_state_no_numbers():
    assert all(not any(ch.isdigit() for ch in e.answer) for e in site_help.ENTRIES)


def test_links_are_internal_paths():
    assert all(href.startswith("/") for e in site_help.ENTRIES for _, href in e.links)


def test_payload_shapes():
    p = site_help.payload(site_help.get("bookmarks"))
    assert p["mode"] == "site_help" and p["id"] == "bookmarks" and "menu" not in p
    assert p["links"] and set(p["links"][0]) == {"label", "href"}
    m = site_help.payload(site_help.get("menu"))
    assert [i["id"] for i in m["menu"]] == [e.id for e in site_help.ENTRIES if e.id != "menu"]


def test_courses_entry_links_to_courses_page():
    e = site_help.get("courses")
    assert ("Courses", "/courses") in e.links
    assert "filter" in e.answer.lower() and "sort" in e.answer.lower()


def test_answers_follow_the_faq():
    # Feedback sits in the phone menu now that the round bottom-right button is the Ask widget.
    assert "in the menu on phones" in site_help.get("report").answer
    assert "round button" not in site_help.get("report").answer
    # The FAQ has no Ask entry under #students.
    assert site_help.get("ask_help").links == (("FAQ", "/faq"),)
    rate = site_help.get("rate").answer
    assert "needs our review first" in rate and "Comments aren't shown on the site yet" in rate


def test_get_unknown_is_none():
    assert site_help.get("nope") is None
