import os

os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest  # noqa: E402

import tag_extractor  # noqa: E402
from tag_extractor import might_have_tags, parse_tag_response, structured_tags, text_supports  # noqa: E402


def test_structured_tags():
    # attendance and textbook were dropped as tags, so those fields no longer make tags
    assert structured_tags({"attendance": "Mandatory", "textbook": "Yes"}) == set()
    assert structured_tags({"attendance": "Not Mandatory", "textbook": "No", "tags": ""}) == set()
    assert structured_tags({"attendance": None, "textbook": None, "tags": None}) == set()
    assert structured_tags({}) == set()


def test_structured_tags_from_rmp_tags():
    row = {"tags": "Tough Grader--Participation matters--EXTRA CREDIT"}
    assert structured_tags(row) == {"participation_grade", "extra_credit"}


def test_parse_drops_bad_tags_and_ids():
    raw = {"1": ["extra_credit", "made_up_tag"], "2": ["curved_grading"], "999": ["easy_a"]}
    assert parse_tag_response(raw, ["1", "2"]) == {"1": ["extra_credit"], "2": ["curved_grading"]}


def test_parse_junk():
    assert parse_tag_response("not json", ["1"]) is None
    assert parse_tag_response(["a list"], ["1"]) is None
    assert parse_tag_response({"1": "easy_a"}, ["1"]) == {}
    assert parse_tag_response({"1": []}, ["1"]) == {}
    assert parse_tag_response('{"5": ["easy_a", "easy_a"]}', [5]) == {"5": ["easy_a"]}


def test_prefilter():
    assert might_have_tags("Attendance is mandatory and he curves the final")
    assert not might_have_tags("Need the TEXTBOOK for hw")  # textbook isn't a tag anymore
    assert not might_have_tags("Great prof, would take again")
    assert not might_have_tags("the final was online and the lecture was easy")
    assert not might_have_tags("")
    assert not might_have_tags(None)


def test_hard_exams_needs_both_words():
    assert text_supports("hard_exams", "the exams were really hard")
    assert not text_supports("hard_exams", "the final project was fun")
    assert not text_supports("hard_exams", "hard working professor")


def test_extract_tags_ollama_down(monkeypatch):
    def fail(_):
        raise ConnectionError("ollama not running")
    monkeypatch.setattr(tag_extractor, "_call_ollama", fail)
    assert tag_extractor.extract_tags([{"id": "1", "text": "curved"}]) is None


def test_extract_tags_bad_json_retries(monkeypatch):
    monkeypatch.setattr(tag_extractor, "_call_ollama", lambda _: "not json")
    assert tag_extractor.extract_tags([{"id": "1", "text": "he curves"}]) is None


def test_extract_tags_filters_output(monkeypatch):
    monkeypatch.setattr(tag_extractor, "_call_ollama",
                        lambda _: '{"1": ["curved_grading", "vibes"], "2": []}')
    out = tag_extractor.extract_tags([{"id": "1", "text": "he curves the final"}, {"id": "2", "text": "b"}])
    assert out == {"1": ["curved_grading"]}


def test_extract_tags_drops_tags_not_in_text(monkeypatch):
    monkeypatch.setattr(tag_extractor, "_call_ollama",
                        lambda _: '{"1": ["extra_credit", "easy_a"]}')
    out = tag_extractor.extract_tags([{"id": "1", "text": "Super easy class, he is very chill"}])
    assert out == {"1": ["easy_a"]}


def test_extract_tags_uses_local_ids(monkeypatch):
    seen = {}

    def fake(prompt):
        seen["prompt"] = prompt
        return '{"2": ["curved_grading"]}'

    monkeypatch.setattr(tag_extractor, "_call_ollama", fake)
    reviews = [{"id": "1100512345678901234", "text": "nice prof"},
               {"id": "1100512345678909999", "text": "he curves"}]
    assert tag_extractor.extract_tags(reviews) == {"1100512345678909999": ["curved_grading"]}
    assert "1100512345678901234" not in seen["prompt"]


@pytest.fixture
def srv(monkeypatch):
    import server
    monkeypatch.setattr(server, "_get_pool",
        lambda: (_ for _ in ()).throw(AssertionError("no DB in test")), raising=False)
    monkeypatch.setattr(server, "cache_get", lambda k: None)
    monkeypatch.setattr(server, "cache_set", lambda k, v: None)
    return server


def test_professor_tags(srv, monkeypatch):
    monkeypatch.setattr(srv, "query_one", lambda sql, params=None: {"slug": "olin-guha", "name_key": "olin guha"})
    seen = {}

    def fake_query(sql, params=None):
        if "review_tags" in sql:
            return [{"tag": "curved_grading", "source_id": "1100512345678901234"},
                    {"tag": "curved_grading", "source_id": "11"}, {"tag": "easy_a", "source_id": "12"}]
        seen["params"] = params
        return [{"tag": "curved_grading", "review_count": 7}, {"tag": "easy_a", "review_count": 3}]

    monkeypatch.setattr(srv, "query", fake_query)
    r = srv.app.test_client().get("/api/professors/olin-guha/tags")
    assert r.status_code == 200
    assert r.get_json() == [
        {"tag": "curved_grading", "count": 7, "reviewIds": ["1100512345678901234", "11"]},
        {"tag": "easy_a", "count": 3, "reviewIds": ["12"]},
    ]
    assert seen["params"] == ("olin guha", srv.MIN_TAG_REVIEWS, srv.MIN_TAG_SHARE, srv.MAX_PROF_TAGS)


def test_professor_tags_404(srv, monkeypatch):
    # denied professors aren't in professors_catalog, so they 404 here same as /full
    monkeypatch.setattr(srv, "query_one", lambda sql, params=None: None)
    assert srv.app.test_client().get("/api/professors/nobody/tags").status_code == 404


def test_popular_tags(srv, monkeypatch):
    seen = {}

    def fake_query(sql, params=None):
        seen["sql"] = sql
        return [{"tag": "mandatory_attendance", "profs": 41}]

    monkeypatch.setattr(srv, "query", fake_query)
    r = srv.app.test_client().get("/api/tags/popular")
    assert r.status_code == 200
    assert r.get_json() == [{"tag": "mandatory_attendance", "count": 41}]
    assert "professors_catalog" in seen["sql"]  # only counts professors that aren't denied


def test_catalog_tag_filter(srv, monkeypatch):
    seen = []

    def fake_query_one(sql, params=None):
        seen.append((sql, params))
        return {"cnt": 0}

    monkeypatch.setattr(srv, "query_one", fake_query_one)
    monkeypatch.setattr(srv, "query", lambda sql, params=None: [])
    r = srv.app.test_client().get("/api/professors-catalog?tags=easy_a|not_a_tag|curved_grading")
    assert r.status_code == 200
    sql, params = seen[0]
    assert sql.count("professor_tags") == 2  # not_a_tag gets dropped
    assert "easy_a" in params and "curved_grading" in params and "not_a_tag" not in params
