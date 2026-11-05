import pytest
from rag import site_help
from rag.chat_gate import MAX_QUERY_LEN

IDS = ["menu", "data_sources", "affiliation", "rate", "goated", "compare", "sentiment",
       "photos", "no_ratings", "missing_course", "offerings", "awards", "report", "search",
       "bookmarks", "departments", "sign_in", "theme", "professors", "privacy", "ask_help"]

SHOULD_MATCH = {
    "menu": ["what can you do", "help", "what is this site", "what is RateMyHusky?"],
    "data_sources": ["where do the ratings come from", "where does the data come from",
                     "how often is the data updated"],
    "affiliation": ["is RateMyHusky run by Northeastern", "is this site affiliated with the university",
                    "is this an official Northeastern website"],
    "rate": ["can I write a review here", "how do I rate a professor", "where is the rating form"],
    "goated": ["how are the GOATED professors ranked", "what does GOATED mean",
               "how is the goated list calculated"],
    "compare": ["how does compare pick the best professor", "what does the compare page do",
                "how do I compare professors"],
    "sentiment": ["what does the sentiment bar mean", "how is the reddit sentiment label generated",
                  "what is the sentiment bar on a comment"],
    "photos": ["why doesn't this instructor have a photo", "where do the faculty photos come from",
               "why is there no picture"],
    "no_ratings": ["why do some pages have no ratings", "why does this instructor have zero reviews",
                   "why is there a page with no ratings"],
    "missing_course": ["why is a course missing from a professor's page",
                       "why isn't a class listed on the page", "a course is missing from the list"],
    "offerings": ["where does last taught come from", "what is when it's offered",
                  "how do I know when a course is offered"],
    "awards": ["where do the teaching award badges come from", "what do the award badges mean",
               "where does award information come from"],
    "report": ["how do I report wrong data", "where is the feedback button",
               "something on the site is wrong"],
    "search": ["how do I search for a professor", "where is the search bar", "how do I find a course"],
    "bookmarks": ["how do I bookmark a professor", "where are my saved professors",
                  "how do bookmarks work"],
    "departments": ["where can I see all departments", "is there a department page",
                    "how do I browse by department"],
    "sign_in": ["how do I sign in", "do I need to log in", "what do I get with a husky account"],
    "theme": ["how do I turn on dark mode", "is there a light theme", "can I change the theme"],
    "professors": ["my professor page is wrong", "how do I get my page removed",
                   "I teach at northeastern, how do I correct my page"],
    "privacy": ["what is your privacy policy", "where are the terms of service",
                "what data do you collect about me"],
    "ask_help": ["what can Ask answer", "what kind of questions can I ask",
                 "how does the ask feature work"],
}
SHOULD_NOT_MATCH = [
    "is CS3500 hard", "how do I get an A in CS2500", "compare Wu and Smith for CS2500",
    "should I bookmark Prof Lee's class", "rate Guha's teaching", "how do I sign up for classes",
    "is professor Lieberherr good at explaining compare and contrast", "who teaches DS 3000",
    "how do I get an A", "is Dr. Wu goated", "is professor Lee's sentiment bar positive",
    "what do you know about Guha", "what do you know about algorithms",
    "i need help choosing a class", "can you help me with a schedule",
    "how is Guha ranked among CS professors",
    "what kind of questions does Guha ask on exams",
    "does Guha have a teaching award badge",
    "why does Guha have no reviews", "something is wrong with Guha's grading",
    "what's the theme of Guha's class", "is Guha official",
    "where does Guha get good reviews from", "how often does Guha update the syllabus",
    "can I write a review for Guha", "is Guha on the goated list",
    "where can I review Guha's syllabus", "is Guha affiliated with the CS department",
    "where does Guha search for funding",
]

def test_registry_has_every_entry():
    assert sorted(e.id for e in site_help.ENTRIES) == sorted(IDS)   # each id exactly once
    assert site_help.ENTRIES[-1].id == "menu"

def test_every_entry_has_three_phrasings():
    assert set(SHOULD_MATCH) == set(IDS)
    assert all(len(v) >= 3 for v in SHOULD_MATCH.values())

@pytest.mark.parametrize("entry_id,q", [(k, q) for k, qs in SHOULD_MATCH.items() for q in qs])
def test_match(entry_id, q):
    hit = site_help.match(q)
    assert hit is not None and hit.id == entry_id

@pytest.mark.parametrize("q", SHOULD_NOT_MATCH)
def test_no_match_on_professor_or_course_questions(q):
    assert site_help.match(q) is None

def test_match_ignores_overlong_text():
    assert site_help.match("how do bookmarks work " + "x" * MAX_QUERY_LEN) is None

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

def test_get_unknown_is_none():
    assert site_help.get("nope") is None
