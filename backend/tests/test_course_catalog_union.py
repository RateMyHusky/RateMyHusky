"""Joining catalog_courses onto the course page.

Two halves, both read-side. `course_catalog` is TRACE-derived and rebuilt
wholesale by precompute.py, so nothing here writes to it — the catalog arrives
as a join at request time.

- A *matched* course (3,889 of 5,199) gains description, credit hours,
  prerequisites and NUpath, and takes the catalog's untruncated title.
- A *catalog-only* course (2,566 after placeholder filtering) gains a page it
  never had, where /courses/:code 404s today.

Every catalog read degrades to today's behaviour on any DB error, because the
tables do not exist on a deploy that predates the loader — including the
rollback, since the pool is not autocommit and a missing-table
ProgrammingError would otherwise poison the next query in the request.
"""

import os

import pytest

os.environ.setdefault("CRDB_DATABASE_URL", "postgresql://stub")
os.environ.setdefault("JWT_SECRET", "test-secret")

CATALOG_ROW = {
    "code": "CS3000", "name": "Algorithms and Data", "department": "Computer Science",
    "credit_hours": "4 Hours", "credit_min": 4.0, "credit_max": 4.0,
    "description": "Introduces the basic principles of efficient algorithms.",
    "prerequisites": "((CS 2100 with a minimum grade of D-))",
    "corequisites": "CS 3001", "catalog_year": "2025-2026", "is_placeholder": False,
}

TRACE_ROW = {"code": "CS3000", "name": "Algorithms  Data", "department": "Khoury",
             "avg_rating": 4.0, "num_responses": 10, "is_topics": False}

SECTION = {
    "course_id": 1, "instructor_id": 10, "term_id": 200, "term_title": "Fall 2024",
    "department_name": "Khoury", "display_name": "CS3000:01 (Algorithms) - Ada Byron",
    "section": "01", "enrollment": 20,
    "instructor_first_name": "Ada", "instructor_last_name": "Byron",
}


def make_client(monkeypatch, trace_row, catalog_row, nupath=(), catalog_raises=False):
    import server

    monkeypatch.setattr(server, "_get_pool",
                        lambda: (_ for _ in ()).throw(AssertionError("no DB in test")),
                        raising=False)
    monkeypatch.setattr(server, "cache_get", lambda key: None, raising=False)
    # 20 requests/second is shared across the whole suite.
    monkeypatch.setattr(server.limiter, "enabled", False)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None, raising=False)

    rolled_back = []

    class FakeConn:
        def rollback(self):
            rolled_back.append(True)

    monkeypatch.setattr(server, "get_db", lambda: FakeConn(), raising=False)

    def fake_query_one(sql, params=()):
        if "FROM catalog_courses" in sql:
            if catalog_raises:
                raise RuntimeError('relation "catalog_courses" does not exist')
            return catalog_row
        if "FROM course_catalog" in sql:
            return trace_row
        raise AssertionError(f"unexpected query_one: {sql}")

    def fake_query(sql, params=()):
        if "FROM catalog_nupath" in sql:
            if catalog_raises:
                raise RuntimeError('relation "catalog_nupath" does not exist')
            return [{"attribute": a} for a in nupath]
        if "FROM trace_courses" in sql:
            return [SECTION] if trace_row else []
        if "GROUP BY course_id, instructor_id, term_id" in sql:
            return [{"course_id": 1, "instructor_id": 10, "term_id": 200,
                     "overall_weighted": 40.0, "overall_responses": 10,
                     "overall_completed": 10, "challeng_weighted": 30.0,
                     "challeng_responses": 10, "hours_weighted": 80.0,
                     "hours_responses": 10}]
        if "FROM professors_catalog" in sql:
            return [{"name_key": "ada byron", "slug": "ada-byron", "image_url": None,
                     "total_reviews": 5, "would_take_again_pct": 80.0,
                     "difficulty": 2.5, "rmp_rating": 4.1}]
        if "FROM rmp_reviews" in sql:
            return []
        if "GROUP BY question" in sql:
            return [{"question": "Overall Rating", "weighted_sum": 40.0,
                     "total_responses": 10}]
        if "UNION ALL" in sql or "FROM trace_comments" in sql:
            return []
        raise AssertionError(f"unexpected query: {sql}")

    monkeypatch.setattr(server, "query_one", fake_query_one, raising=False)
    monkeypatch.setattr(server, "query", fake_query, raising=False)
    return server.app.test_client(), rolled_back


def get_course(monkeypatch, trace_row=TRACE_ROW, catalog_row=CATALOG_ROW, **kw):
    client, _ = make_client(monkeypatch, trace_row, catalog_row, **kw)
    return client.get("/api/courses/CS3000")


# --- a matched course gains the catalog's fields ---

def test_matched_course_gains_the_description(monkeypatch):
    data = get_course(monkeypatch).get_json()
    assert data["summary"]["description"].startswith("Introduces the basic principles")


def test_matched_course_gains_credits_and_requisites(monkeypatch):
    s = get_course(monkeypatch).get_json()["summary"]
    assert s["creditHours"] == "4 Hours"
    assert s["prerequisites"] == "((CS 2100 with a minimum grade of D-))"
    assert s["corequisites"] == "CS 3001"


def test_matched_course_gains_nupath(monkeypatch):
    data = get_course(monkeypatch, nupath=["Formal/Quant Reasoning"]).get_json()
    assert data["summary"]["nupath"] == ["Formal/Quant Reasoning"]


def test_the_catalog_title_replaces_the_truncated_trace_one(monkeypatch):
    """TRACE caps titles at 30 chars and drops '&'; the catalog is the record."""
    data = get_course(monkeypatch).get_json()
    assert data["summary"]["name"] == "Algorithms and Data"


def test_trace_ratings_are_untouched_by_the_join(monkeypatch):
    """The catalog has no ratings and must never influence them."""
    s = get_course(monkeypatch).get_json()["summary"]
    assert s["avgRating"] == 4.0
    assert s["ratingCount"] == 10


def test_the_page_shows_the_same_department_as_the_course_list(monkeypatch):
    """The list and its filter use the catalog's department; the page must too,
    or CS3000 is "Computer Science" in the list and "Khoury" when opened."""
    s = get_course(monkeypatch).get_json()["summary"]
    assert s["department"] == "Computer Science"


def test_without_the_catalog_the_page_keeps_traces_department(monkeypatch):
    s = get_course(monkeypatch, catalog_raises=True).get_json()["summary"]
    assert s["department"] == "Khoury"


# --- a catalog-only course gains a page ---

def test_a_catalog_only_course_serves_a_page(monkeypatch):
    """No TRACE row at all — this is the dead-chip fix."""
    resp = get_course(monkeypatch, trace_row=None)
    assert resp.status_code == 200
    s = resp.get_json()["summary"]
    assert s["code"] == "CS3000"
    assert s["name"] == "Algorithms and Data"
    assert s["description"].startswith("Introduces")


def test_a_catalog_only_course_has_no_rating_and_no_instructors(monkeypatch):
    data = get_course(monkeypatch, trace_row=None).get_json()
    assert data["summary"]["avgRating"] is None
    assert data["summary"]["ratingCount"] is None
    assert data["instructors"] == []


def test_a_catalog_only_course_says_it_is_unrated(monkeypatch):
    """The page has to explain the missing rating rather than show a blank."""
    data = get_course(monkeypatch, trace_row=None).get_json()
    assert data["summary"]["unrated"] is True


def test_a_rated_course_is_not_marked_unrated(monkeypatch):
    assert get_course(monkeypatch).get_json()["summary"]["unrated"] is False


def test_a_placeholder_catalog_only_course_gets_no_page(monkeypatch):
    """849 'Elective' rows must not become 849 pages."""
    placeholder = {**CATALOG_ROW, "name": "Elective", "is_placeholder": True}
    resp = get_course(monkeypatch, trace_row=None, catalog_row=placeholder)
    assert resp.status_code == 404


def test_a_placeholder_that_trace_rated_still_gets_its_page(monkeypatch):
    """is_placeholder is advisory: ratings override it (11 x99x codes are real)."""
    placeholder = {**CATALOG_ROW, "name": "Thesis", "is_placeholder": True}
    resp = get_course(monkeypatch, trace_row=TRACE_ROW, catalog_row=placeholder)
    assert resp.status_code == 200


def test_a_code_in_neither_table_is_still_a_404(monkeypatch):
    resp = get_course(monkeypatch, trace_row=None, catalog_row=None)
    assert resp.status_code == 404


# --- degradation: the tables do not exist on an older deploy ---

def test_a_missing_catalog_table_leaves_the_page_exactly_as_it_was(monkeypatch):
    resp = get_course(monkeypatch, catalog_raises=True)
    assert resp.status_code == 200
    s = resp.get_json()["summary"]
    assert s["avgRating"] == 4.0
    assert s["description"] is None
    assert s["nupath"] == []
    assert s["name"] == "Algorithms  Data"      # falls back to the TRACE title


def test_a_missing_catalog_table_rolls_back_so_later_queries_survive(monkeypatch):
    """Without this the next query raises InFailedSqlTransaction and 500s."""
    client, rolled_back = make_client(monkeypatch, TRACE_ROW, None, catalog_raises=True)
    assert client.get("/api/courses/CS3000").status_code == 200
    assert rolled_back, "a failed catalog lookup must roll the connection back"


def test_a_missing_catalog_table_cannot_resurrect_a_404(monkeypatch):
    resp = get_course(monkeypatch, trace_row=None, catalog_raises=True)
    assert resp.status_code == 404


# --- the department vocabulary ---
#
# Lives in test_course_department_agreement.py, which runs the endpoints' real
# SQL (sqlite in CI, optionally a live database) instead of matching on SQL
# text — text-matching fakes let the dropdown and the course filter drift apart
# while each passed on its own.
