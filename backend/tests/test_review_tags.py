import os

os.environ.setdefault("CRDB_DATABASE_URL", "postgresql://stub")
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest  # noqa: E402

import tag_extractor  # noqa: E402
from tag_extractor import might_have_tags, parse_tag_response, structured_tags  # noqa: E402


# ── structured RMP fields ──

def test_structured_attendance_and_textbook():
    assert structured_tags({"attendance": "Mandatory", "textbook": "Yes"}) == {
        "mandatory_attendance", "requires_textbook"}


def test_structured_negatives_and_blanks():
    assert structured_tags({"attendance": "Not Mandatory", "textbook": "No", "tags": ""}) == set()
    assert structured_tags({"attendance": None, "textbook": None, "tags": None}) == set()
    assert structured_tags({}) == set()


def test_structured_rmp_tags():
    row = {"tags": "Tough Grader--Participation matters--EXTRA CREDIT"}
    assert structured_tags(row) == {"participation_grade", "extra_credit"}


# ── model output handling (no model, no DB) ──

def test_parse_drops_unknown_tags_and_ids():
    raw = {"1": ["mandatory_attendance", "made_up_tag"], "2": ["curved_grading"], "999": ["easy_a"]}
    assert parse_tag_response(raw, ["1", "2"]) == {"1": ["mandatory_attendance"], "2": ["curved_grading"]}


def test_parse_handles_junk():
    assert parse_tag_response("not json", ["1"]) == {}
    assert parse_tag_response(["a list"], ["1"]) == {}
    assert parse_tag_response({"1": "easy_a"}, ["1"]) == {}
    assert parse_tag_response({"1": []}, ["1"]) == {}


def test_parse_accepts_json_string_and_int_ids():
    assert parse_tag_response('{"5": ["easy_a", "easy_a"]}', [5]) == {"5": ["easy_a"]}


def test_prefilter():
    assert might_have_tags("Attendance is mandatory and he curves the final")
    assert might_have_tags("Need the TEXTBOOK for hw")
    assert not might_have_tags("Great prof, would take again")
    assert not might_have_tags("")
    assert not might_have_tags(None)


def test_extract_returns_none_when_call_fails(monkeypatch):
    def boom(_):
        raise ConnectionError("ollama not running")
    monkeypatch.setattr(tag_extractor, "_call_ollama", boom)
    assert tag_extractor.extract_tags([{"id": "1", "text": "curved"}]) is None


def test_extract_validates_model_output(monkeypatch):
    monkeypatch.setattr(tag_extractor, "_call_ollama",
                        lambda _: '{"1": ["curved_grading", "vibes"], "2": []}')
    out = tag_extractor.extract_tags([{"id": "1", "text": "a"}, {"id": "2", "text": "b"}])
    assert out == {"1": ["curved_grading"]}


# ── routes ──

@pytest.fixture
def srv(monkeypatch):
    import server
    monkeypatch.setattr(server, "_get_pool",
        lambda: (_ for _ in ()).throw(AssertionError("no DB in test")), raising=False)
    monkeypatch.setattr(server, "cache_get", lambda k: None)
    monkeypatch.setattr(server, "cache_set", lambda k, v: None)
    return server


def test_professor_tags(srv, monkeypatch):
    monkeypatch.setattr(srv, "query_one", lambda sql, params=None: {"name_key": "olin guha"})
    seen = {}

    def fake_query(sql, params=None):
        seen["params"] = params
        return [{"tag": "curved_grading", "review_count": 7}, {"tag": "easy_a", "review_count": 3}]

    monkeypatch.setattr(srv, "query", fake_query)
    r = srv.app.test_client().get("/api/professors/olin-guha/tags")
    assert r.status_code == 200
    assert r.get_json() == [{"tag": "curved_grading", "count": 7}, {"tag": "easy_a", "count": 3}]
    assert seen["params"] == ("olin guha", srv.MIN_TAG_REVIEWS)


def test_professor_tags_404(srv, monkeypatch):
    monkeypatch.setattr(srv, "query_one", lambda sql, params=None: None)
    assert srv.app.test_client().get("/api/professors/nobody/tags").status_code == 404


def test_popular_tags(srv, monkeypatch):
    monkeypatch.setattr(srv, "query", lambda sql, params=None: [{"tag": "mandatory_attendance", "profs": 41}])
    r = srv.app.test_client().get("/api/tags/popular")
    assert r.status_code == 200
    assert r.get_json() == [{"tag": "mandatory_attendance", "count": 41}]
