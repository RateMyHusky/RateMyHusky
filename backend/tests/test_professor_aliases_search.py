"""Approved nicknames find a professor, and only ever as a way to find the slug."""

import os

import pytest

os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
import server  # noqa: E402

TSEK = {"slug": "iraklis-tsekourakis", "name": "Iraklis Tsekourakis",
        "name_key": "iraklis tsekourakis", "department": "Khoury",
        "avg_rating": 4.0, "total_reviews": 3}
OTHER = {"slug": "herc-jones", "name": "Hercules Jones", "name_key": "hercules jones",
         "department": "Khoury", "avg_rating": 3.0, "total_reviews": 9}
POOL = [TSEK, OTHER, {"slug": "other-tsek", "name": "Ann Tsek", "name_key": "ann tsek",
                      "department": None, "avg_rating": None, "total_reviews": 1}]


@pytest.fixture
def stub(monkeypatch):
    """server.query with an alias table and a catalog; records every call."""
    state = {"aliases": [], "calls": [], "search_sql": []}

    def fake_query(sql, params=None):
        state["calls"].append(sql)
        if "professor_aliases" in sql:
            return state["aliases"]
        state["search_sql"].append(sql)
        where = params[:-2]  # the last two params belong to the ORDER BY
        slugs = next((p for p in where if isinstance(p, list)), [])
        likes = [p.strip("%") for p in where if isinstance(p, str)]
        if "slug = ANY" in sql:
            # one alias word plus one name word, or only the alias word
            name_words = likes
            return [r for r in POOL
                    if (r["slug"] in slugs) and all(w in r["name_key"] for w in name_words if w != "herc")]
        return [r for r in POOL if all(w in r["name_key"] for w in likes)]

    monkeypatch.setattr(server, "query", fake_query)
    monkeypatch.setattr(server, "data_version", lambda: 1)
    server._reset_alias_cache()
    yield state
    server._reset_alias_cache()


def search(q):
    resp = server.app.test_client().get(f"/api/search?q={q}")
    assert resp.status_code == 200
    return resp


def test_a_one_word_alias_finds_the_professor_under_the_formal_name(stub):
    stub["aliases"] = [{"alias_key": "herc", "slug": "iraklis-tsekourakis"}]
    resp = search("herc")
    results = resp.get_json()
    assert [r["name"] for r in results] == ["Iraklis Tsekourakis"] or \
        results[0]["name"] == "Iraklis Tsekourakis"
    assert "herc" not in resp.get_data(as_text=True).lower().replace("hercules", "")
    assert "slug = ANY(%s)" in stub["search_sql"][0]


def test_an_alias_and_a_name_word_together_still_match(stub):
    stub["aliases"] = [{"alias_key": "herc", "slug": "iraklis-tsekourakis"}]
    results = search("herc%20tsek").get_json()
    assert [r["name"] for r in results] == ["Iraklis Tsekourakis"]


def test_an_alias_for_two_professors_lists_both(stub):
    stub["aliases"] = [{"alias_key": "herc", "slug": "iraklis-tsekourakis"},
                       {"alias_key": "herc", "slug": "other-tsek"}]
    results = search("herc").get_json()
    assert {r["slug"] for r in results} == {"iraklis-tsekourakis", "other-tsek"}


def test_alias_rows_rank_first(stub, monkeypatch):
    stub["aliases"] = [{"alias_key": "herc", "slug": "iraklis-tsekourakis"}]
    monkeypatch.setattr(server, "query", lambda sql, params=None:
                        stub["aliases"] if "professor_aliases" in sql else [OTHER, TSEK])
    server._reset_alias_cache()
    assert [r["slug"] for r in server._professor_search("herc")][0] == "iraklis-tsekourakis"


def test_the_alias_cache_reloads_after_the_ttl_and_survives_a_db_error(stub, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(server.time, "time", lambda: now[0])
    stub["aliases"] = [{"alias_key": "herc", "slug": "iraklis-tsekourakis"}]
    search("herc")
    search("herc")
    assert sum("professor_aliases" in c for c in stub["calls"]) == 1

    now[0] += server.ALIAS_TTL_SECONDS + 1
    stub["aliases"] = []
    search("herc")
    assert sum("professor_aliases" in c for c in stub["calls"]) == 2
    assert server._approved_aliases() == {}

    stub["aliases"] = [{"alias_key": "herc", "slug": "iraklis-tsekourakis"}]
    now[0] += server.ALIAS_TTL_SECONDS + 1
    search("herc")
    assert server._approved_aliases() == {"herc": ["iraklis-tsekourakis"]}

    def boom(sql, params=None):
        if "professor_aliases" in sql:
            raise RuntimeError("db down")
        return []
    monkeypatch.setattr(server, "query", boom)
    now[0] += server.ALIAS_TTL_SECONDS + 1
    search("herc")
    assert server._approved_aliases() == {"herc": ["iraklis-tsekourakis"]}


def test_the_alias_cache_reloads_when_the_data_version_moves(stub, monkeypatch):
    version = [1]
    monkeypatch.setattr(server, "data_version", lambda: version[0])
    stub["aliases"] = [{"alias_key": "herc", "slug": "iraklis-tsekourakis"}]
    assert server._approved_aliases() == {"herc": ["iraklis-tsekourakis"]}
    stub["aliases"] = []
    assert server._approved_aliases() == {"herc": ["iraklis-tsekourakis"]}  # same version, inside the TTL
    version[0] = 2
    assert server._approved_aliases() == {}
    assert sum("professor_aliases" in c for c in stub["calls"]) == 2


def test_a_search_during_another_requests_reload_uses_the_last_map(stub, monkeypatch):
    version = [1]
    monkeypatch.setattr(server, "data_version", lambda: version[0])
    stub["aliases"] = [{"alias_key": "herc", "slug": "iraklis-tsekourakis"}]
    assert server._approved_aliases() == {"herc": ["iraklis-tsekourakis"]}
    stub["aliases"] = []
    version[0] = 2
    assert server._alias_lock.acquire(blocking=False)  # another request is reloading
    try:
        assert server._approved_aliases() == {"herc": ["iraklis-tsekourakis"]}
    finally:
        server._alias_lock.release()
    assert sum("professor_aliases" in c for c in stub["calls"]) == 1
    assert server._approved_aliases() == {}


def test_a_failed_alias_load_is_logged(stub, monkeypatch, capsys):
    def boom(sql, params=None):
        raise RuntimeError("db down")
    monkeypatch.setattr(server, "query", boom)
    assert server._approved_aliases() == {}
    out = capsys.readouterr().out
    assert "approved aliases: load failed" in out and "db down" in out


def test_the_order_by_puts_alias_hits_ahead_of_the_100_row_cut(monkeypatch):
    seen = []
    monkeypatch.setattr(server, "query", lambda sql, params=None:
                        [] if "professor_aliases" in sql else seen.append((sql, params)) or [])
    server._reset_alias_cache()
    monkeypatch.setattr(server, "_approved_aliases", lambda: {"herc": ["b-slug", "a-slug"]})
    server._professor_search("herc")
    sql, params = seen[0]
    assert sql.split("ORDER BY ")[1].startswith("(slug = ANY(%s)) DESC, ")
    assert params[-3] == ["a-slug", "b-slug"]

    monkeypatch.setattr(server, "_approved_aliases", lambda: {})
    server._professor_search("herc")
    assert "slug = ANY" not in seen[1][0]
