"""Tests for comment moderation.

The module itself with a fake client so nothing dials out, then the /reviews
route (test_bookmarks_api.py pattern) — a filter that passes its unit tests but
never got wired into the read path is worse than no filter at all.
"""

import os

import pytest

import moderation


# ── classify: thresholds ──

def test_clean_scores_allow():
    assert moderation.classify({"harassment": 0.01}).action == "allow"
    assert moderation.classify({}).action == "allow"


def test_threatening_content_blocks():
    assert moderation.classify({"harassment/threatening": 0.9}).action == "block"
    assert moderation.classify({"hate": 0.7}).action == "block"
    assert moderation.classify({"sexual/minors": 0.3}).action == "block"


def test_block_reports_the_category_that_tripped():
    v = moderation.classify({"hate": 0.7, "violence": 0.9})
    assert "hate" in v.reason and "violence" in v.reason


def test_harsh_review_is_not_blocked():
    """If plain harassment ever starts blocking, the filter eats the product."""
    v = moderation.classify({"harassment": 0.75})
    assert v.action != "block"
    assert moderation.is_published(v.action)


def test_borderline_lands_in_review_band():
    assert moderation.classify({"harassment": 0.95}).action == "review"


def test_is_published():
    assert moderation.is_published("allow") is True
    assert moderation.is_published("block") is False
    assert moderation.is_published("review") is (not moderation.REVIEW_HIDES)


# ── score_texts: batching, ordering, failure ──

class FakeClient:
    """Records each batch, so the batching assertions have something to read."""

    def __init__(self, score_for):
        self.score_for = score_for
        self.batches = []

    class _Moderations:
        def __init__(self, outer):
            self.outer = outer

        def create(self, model, input):
            self.outer.batches.append(list(input))
            results = [type("Res", (), {"category_scores": self.outer.score_for(t)})()
                       for t in input]
            return type("Resp", (), {"results": results})()

    @property
    def moderations(self):
        return FakeClient._Moderations(self)


def _client(flag_substring="slur"):
    return FakeClient(
        lambda t: {"hate": 0.9} if flag_substring in t else {"hate": 0.0}
    )


def test_score_texts_returns_one_verdict_per_input_in_order():
    client = _client()
    out = moderation.score_texts(["ok", "slur", "fine"], client=client)
    assert [v.action for v in out] == ["allow", "block", "allow"]


def test_score_texts_batches_requests():
    client = _client()
    texts = [f"comment {i}" for i in range(250)]
    out = moderation.score_texts(texts, client=client)
    assert len(out) == 250
    assert len(client.batches) == 3
    assert [len(b) for b in client.batches] == [100, 100, 50]


def test_score_texts_no_call_for_empty_input():
    client = _client()
    assert moderation.score_texts([], client=client) == []
    assert client.batches == []


def test_score_texts_handles_none_text():
    client = _client()
    out = moderation.score_texts([None, "ok"], client=client)
    assert len(out) == 2


def test_transport_failure_raises_rather_than_passing_content():
    class Broken:
        @property
        def moderations(self):
            raise RuntimeError("network down")

    with pytest.raises(moderation.ModerationUnavailable):
        moderation.score_texts(["anything"], client=Broken())


def test_result_count_mismatch_raises():
    class Short:
        class _M:
            def create(self, model, input):
                return type("Resp", (), {"results": []})()

        @property
        def moderations(self):
            return Short._M()

    with pytest.raises(moderation.ModerationUnavailable):
        moderation.score_texts(["a", "b"], client=Short())


def test_slashed_categories_survive_the_sdk_model():
    """The SDK hands back a pydantic model whose field names are underscored
    (harassment_threatening), while our thresholds use the API's slashed names.
    Dump it without the aliases and every severe category silently reads 0.0.

    Every 0.99 below is a slashed or hyphenated category; everything plain is
    0.01. So this only passes if the aliases survive the round trip.
    """
    from openai.types.moderation import CategoryScores

    api_shaped = {
        "harassment": 0.01, "harassment/threatening": 0.99,
        "hate": 0.01, "hate/threatening": 0.99,
        "illicit": 0.01, "illicit/violent": 0.99,
        "self-harm": 0.01, "self-harm/intent": 0.01, "self-harm/instructions": 0.99,
        "sexual": 0.01, "sexual/minors": 0.99,
        "violence": 0.01, "violence/graphic": 0.99,
    }

    class SdkShaped:
        class _M:
            def create(self, model, input):
                scores = CategoryScores.model_validate(api_shaped)
                results = [type("Res", (), {"category_scores": scores})() for _ in input]
                return type("Resp", (), {"results": results})()

        @property
        def moderations(self):
            return SdkShaped._M()

    verdict = moderation.score_texts(["anything"], client=SdkShaped())[0]
    assert verdict.action == "block"

    for category in ("harassment/threatening", "hate/threatening", "sexual/minors",
                     "self-harm/instructions", "violence/graphic", "illicit/violent"):
        assert category in verdict.reason, f"{category} never fired"


# ── SQL predicate ──

@pytest.fixture
def enforcing(monkeypatch):
    monkeypatch.setenv("MODERATION_ENFORCE", "true")


@pytest.fixture
def not_enforcing(monkeypatch):
    monkeypatch.setenv("MODERATION_ENFORCE", "false")


def test_filter_is_empty_when_not_enforcing(not_enforcing):
    assert moderation.sql_filter() == ""
    assert moderation.sql_filter("t") == ""


def test_filter_excludes_blocked_and_unscored(enforcing):
    f = moderation.sql_filter()
    assert f.lstrip().startswith("AND")
    assert "'block'" in f
    assert "mod_checked_at IS NOT NULL" in f


def test_filter_applies_table_alias(enforcing):
    assert "t.mod_action" in moderation.sql_filter("t")
    assert "t.mod_checked_at" in moderation.sql_filter("t")


def test_filter_honours_review_hides(enforcing):
    assert ("'review'" in moderation.sql_filter()) is moderation.REVIEW_HIDES


# ── Route wiring:  /api/professors/<slug>/full ──

@pytest.fixture
def reviews_client(monkeypatch):
    os.environ.setdefault("CRDB_DATABASE_URL", "postgresql://stub")
    os.environ.setdefault("JWT_SECRET", "test-secret")
    import server

    monkeypatch.setattr(server, "_get_pool",
                        lambda: (_ for _ in ()).throw(AssertionError("no DB in test")),
                        raising=False)
    monkeypatch.setattr(server, "cache_get", lambda key: None, raising=False)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None, raising=False)

    seen = {"sql": []}

    def fake_query(sql, params=()):
        seen["sql"].append(sql)
        if "FROM rmp_reviews" in sql:
            return [{
                "course": "CS2500", "quality": 2.0, "difficulty": 5.0,
                "date": "2025-01-01", "tags": "", "attendance": "",
                "grade": "B", "textbook": "", "online_class": "",
                "comment": "Brutal curve, no partial credit.",
            }]
        if "FROM source_summary" in sql:
            return []
        raise AssertionError(f"unexpected query: {sql}")

    def fake_query_one(sql, params=()):
        if "FROM professors_catalog" in sql:
            return {"slug": "alice-smith", "name": "Alice Smith", "name_key": "alice smith",
                    "department": "Khoury", "num_ratings": 1, "rmp_rating": 2.0}
        raise AssertionError(f"unexpected query_one: {sql}")

    monkeypatch.setattr(server, "query", fake_query, raising=False)
    monkeypatch.setattr(server, "query_one", fake_query_one, raising=False)
    monkeypatch.setattr(server, "fetch_reddit_mentions",
                        lambda slug, q, mod_filter="": [], raising=False)
    return server.app.test_client(), seen


def test_reviews_route_returns_comment_text_unchanged(reviews_client):
    client, _ = reviews_client
    resp = client.get("/api/professors/alice-smith/full")
    assert resp.status_code == 200
    assert resp.get_json()["sources"]["rmp"]["reviews"][0]["comment"] == "Brutal curve, no partial credit."


def test_reviews_route_applies_filter_when_enforcing(reviews_client, enforcing):
    client, seen = reviews_client
    client.get("/api/professors/alice-smith/full")
    rmp_sql = [s for s in seen["sql"] if "FROM rmp_reviews" in s]
    assert rmp_sql, "the full route never queried rmp_reviews"
    assert "mod_action" in rmp_sql[0]


def test_reviews_route_unfiltered_when_not_enforcing(reviews_client, not_enforcing):
    client, seen = reviews_client
    client.get("/api/professors/alice-smith/full")
    rmp_sql = [s for s in seen["sql"] if "FROM rmp_reviews" in s]
    assert rmp_sql
    assert "mod_action" not in rmp_sql[0]


# ── Route wiring:  /api/chat?mode=keyword ──
#
# Keyword is the default mode and is not sign-in gated, so it is the most
# exposed read path in the app. It reached production filtering only on
# t.flagged, which let blocked Reddit text stay searchable.

@pytest.fixture
def chat_client(monkeypatch):
    os.environ.setdefault("CRDB_DATABASE_URL", "postgresql://stub")
    os.environ.setdefault("JWT_SECRET", "test-secret")
    import server

    monkeypatch.setattr(server, "_get_pool",
                        lambda: (_ for _ in ()).throw(AssertionError("no DB in test")),
                        raising=False)

    seen = {"sql": []}

    def fake_query(sql, params=()):
        seen["sql"].append(sql)
        return []

    monkeypatch.setattr(server, "query", fake_query, raising=False)
    monkeypatch.setattr(server, "_professor_search", lambda q, limit=5: [], raising=False)
    return server.app.test_client(), seen


def test_keyword_search_applies_filter_when_enforcing(chat_client, enforcing):
    client, seen = chat_client
    assert client.get("/api/chat?q=guha&mode=keyword").status_code == 200
    reddit_sql = [s for s in seen["sql"] if "FROM reddit_text" in s]
    assert reddit_sql, "keyword search never queried reddit_text"
    assert "mod_action" in reddit_sql[0]


def test_keyword_search_unfiltered_when_not_enforcing(chat_client, not_enforcing):
    client, seen = chat_client
    client.get("/api/chat?q=guha&mode=keyword")
    reddit_sql = [s for s in seen["sql"] if "FROM reddit_text" in s]
    assert reddit_sql
    assert "mod_action" not in reddit_sql[0]
