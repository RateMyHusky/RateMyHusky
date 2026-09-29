"""Multi-select filters are joined with "|", never ",".

Department names carry commas — "Lang, Literature and Culture" and "Dean of
Coll of Arts, Media" in TRACE and professors_catalog, "Women's, Gender, and
Sexuality Studies" in the catalog — so a comma-joined selection splits one
name into fragments that match nothing. The frontend joins with the same
character (FILTER_SEPARATOR in Courses.tsx and ProfessorCatalog.tsx).
"""

import os

import pytest

os.environ.setdefault("CRDB_DATABASE_URL", "postgresql://stub")
os.environ.setdefault("JWT_SECRET", "test-secret")

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


class _Stop(Exception):
    pass


@pytest.fixture
def professor_params(monkeypatch):
    """The parameters /api/professors-catalog hands the database for its count query."""
    seen = []

    def capture(sql, params=None):
        seen.append(list(params or []))
        raise _Stop

    monkeypatch.setattr(server, "query_one", capture)
    monkeypatch.setattr(server, "query", capture)
    monkeypatch.setattr(server, "cache_get", lambda key: None)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None)
    monkeypatch.setattr(server.limiter, "enabled", False)
    monkeypatch.setitem(server.app.config, "PROPAGATE_EXCEPTIONS", True)

    def get(**args):
        with pytest.raises(_Stop):
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
