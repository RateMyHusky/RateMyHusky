"""Multi-select filters are joined with "|", never ",".

Department names carry commas ("Lang, Literature and Culture", "Women's,
Gender, and Sexuality Studies"), so a comma-joined selection splits one name
into fragments that match nothing. The frontend joins with the same character
(FILTER_SEPARATOR in api.ts).
"""

import os

import pytest

os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
import server  # noqa: E402


def test_a_name_with_commas_stays_whole():
    assert server.split_filter("Lang, Literature and Culture") == ["Lang, Literature and Culture"]


def test_values_split_on_the_separator():
    assert server.split_filter("Khoury|Lang, Literature and Culture") == [
        "Khoury", "Lang, Literature and Culture"]


def test_blank_and_padded_values_are_dropped_and_trimmed():
    assert server.split_filter(" Khoury || Economics |") == ["Khoury", "Economics"]


def test_empty_input_selects_nothing():
    assert server.split_filter("") == []


@pytest.fixture
def professor_params(monkeypatch):
    """The parameters /api/professors-catalog hands the database for its count query."""
    seen = []

    def capture(sql, params=None):
        seen.append(list(params or []))
        raise RuntimeError("stop after the first statement")

    monkeypatch.setattr(server, "query_one", capture)
    monkeypatch.setattr(server, "query", capture)
    monkeypatch.setattr(server, "cache_get", lambda key: None)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None)
    monkeypatch.setattr(server.limiter, "enabled", False)

    def get(**args):
        server.app.test_client().get("/api/professors-catalog", query_string=args)
        return seen[0]

    return get


def test_professor_department_with_a_comma_is_one_parameter(professor_params):
    assert "Lang, Literature and Culture" in professor_params(dept="Lang, Literature and Culture")


def test_professor_departments_split_on_the_separator(professor_params):
    params = professor_params(dept="Lang, Literature and Culture|Economics")
    assert "Lang, Literature and Culture" in params and "Economics" in params


def test_professor_colleges_split_on_the_separator(professor_params):
    params = professor_params(college="Khoury|CSSH")
    assert "Khoury" in params and "CSSH" in params


def test_search_keeps_a_zero_review_professor_whose_name_starts_with_the_query(monkeypatch):
    """The 100-row cut runs in SQL before Python ranks, so with more substring
    matches than the cut it must order word-start matches first, not by reviews."""
    pool = [{"slug": f"s{i}", "name": f"Xlee{i} Smith", "name_key": f"xlee{i} smith",
             "department": "D", "avg_rating": 4.0, "total_reviews": 50} for i in range(120)]
    pool.append({"slug": "banner", "name": "Ann Lee", "name_key": "ann lee",
                 "department": None, "avg_rating": None, "total_reviews": 0})

    def fake_query(sql, params=None):
        *like, starts, word_starts = params
        rows = [r for r in pool if all(p.strip("%") in r["name_key"] for p in like)]
        # Honor the cut the way Postgres would: the ORDER BY decides who survives.
        assert "ORDER BY (name_key LIKE %s OR name_key LIKE %s) DESC, total_reviews DESC" in sql
        rows.sort(key=lambda r: (
            not (r["name_key"].startswith(starts[:-1]) or (" " + starts[:-1]) in " " + r["name_key"]),
            -r["total_reviews"]))
        return rows[:100]

    monkeypatch.setattr(server, "query", fake_query)
    monkeypatch.setattr(server, "_approved_aliases", lambda: {})
    assert server._professor_search("lee", limit=5)[0]["slug"] == "banner"


def test_rated_only_search_filters_before_the_cut(monkeypatch):
    """The catalog page keeps only rated rows, so it must drop unrated ones in SQL
    or they fill the 100-row cut and push rated matches out."""
    seen = []
    monkeypatch.setattr(server, "query", lambda sql, params=None: seen.append(sql) or [])
    monkeypatch.setattr(server, "_approved_aliases", lambda: {})
    server._professor_search("lee", limit=200, rated_only=True)
    server._professor_search("lee", limit=5)
    assert "avg_rating IS NOT NULL" in seen[0].split("ORDER BY")[0]
    assert "avg_rating IS NOT NULL" not in seen[1]
