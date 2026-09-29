"""A fuzzy-matched instructor keeps their profile link on a course page.

TRACE files "Daniel Koloski"; the catalog row is keyed by RMP's "dan koloski"
and records TRACE's spelling in trace_name_key. course_profile looks instructors
up by TRACE's spelling, so a name_key-only lookup found nothing and the card
rendered as "profile unavailable" with no photo or counts. It only worked before
because precompute also wrote a duplicate TRACE-only row, which it now absorbs.

RMP-side numbers (difficulty for this course, comment counts) are stored under
the RMP spelling, so they have to be looked up by the catalog row's name_key.
"""

import os

import pytest

KOLOSKI = {"name_key": "dan koloski", "trace_name_key": "daniel koloski",
           "slug": "dan-koloski", "image_url": "http://img/dk.jpg",
           "total_reviews": 40, "would_take_again_pct": 90.0,
           "difficulty": 2.0, "rmp_rating": 4.5}


def make_client(monkeypatch, has_trace_column=True):
    os.environ.setdefault("CRDB_DATABASE_URL", "postgresql://stub")
    os.environ.setdefault("JWT_SECRET", "test-secret")
    import psycopg2.errors
    import server

    monkeypatch.setattr(server, "_get_pool", lambda: (_ for _ in ()).throw(AssertionError("no DB in test")), raising=False)
    monkeypatch.setattr(server, "cache_get", lambda key: None, raising=False)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None, raising=False)
    # 20 requests/second is shared across the whole suite.
    monkeypatch.setattr(server.limiter, "enabled", False)

    class Conn:
        rollbacks = 0

        def rollback(self):
            Conn.rollbacks += 1

    monkeypatch.setattr(server, "get_db", lambda: Conn(), raising=False)

    section = {
        "course_id": 1, "instructor_id": 10, "term_id": 200,
        "term_title": "Fall 2024", "department_name": "Communication Studies",
        "display_name": "COMM1101:01 (Public Speaking) - Daniel Koloski",
        "section": "01", "enrollment": 20,
        "instructor_first_name": "Daniel", "instructor_last_name": "Koloski",
    }
    seen = {"rmp_keys": []}

    def fake_query_one(sql, params=()):
        if "FROM course_catalog" in sql:
            return {"code": "COMM1101", "name": "Public Speaking",
                    "department": "Communication Studies",
                    "avg_rating": 4.0, "num_responses": 10}
        if "FROM catalog_courses" in sql:
            return None  # no NEU catalog row; keeps rollbacks to the one under test
        raise AssertionError(f"unexpected query_one: {sql}")

    def fake_query(sql, params=()):
        if "FROM trace_comments" in sql:
            return [{"name_key": "daniel koloski", "cnt": 3}]
        if "FROM trace_courses" in sql:
            return [section]
        if "GROUP BY course_id, instructor_id, term_id" in sql:
            return [{
                "course_id": 1, "instructor_id": 10, "term_id": 200,
                "overall_weighted": 40.0, "overall_responses": 10, "overall_completed": 10,
                "challeng_weighted": 30.0, "challeng_responses": 10,
                "hours_weighted": 80.0, "hours_responses": 10,
            }]
        if "FROM professors_catalog WHERE trace_name_key" in sql:
            if not has_trace_column:
                raise psycopg2.errors.UndefinedColumn("column trace_name_key does not exist")
            return [KOLOSKI] if "daniel koloski" in params else []
        if "FROM professors_catalog" in sql:
            return []  # nobody is keyed "daniel koloski"
        if "FROM rmp_reviews" in sql:
            seen["rmp_keys"].extend(p for p in params if isinstance(p, str))
            if "AVG(CAST(difficulty" in sql and "dan koloski" in params:
                return [{"name_key": "dan koloski", "avg_diff": 1.0}]
            if "COUNT(*)" in sql and "dan koloski" in params:
                return [{"name_key": "dan koloski", "cnt": 5}]
            return []
        if "GROUP BY question" in sql:
            return [{"question": "Overall Rating", "weighted_sum": 40.0, "total_responses": 10}]
        raise AssertionError(f"unexpected query: {sql}")

    monkeypatch.setattr(server, "query_one", fake_query_one, raising=False)
    monkeypatch.setattr(server, "query", fake_query, raising=False)
    return server.app.test_client(), seen, Conn


def instructor(monkeypatch, **kw):
    client, seen, conn = make_client(monkeypatch, **kw)
    resp = client.get("/api/courses/COMM1101")
    assert resp.status_code == 200
    [row] = resp.get_json()["instructors"]
    return row, seen, conn


def test_fuzzy_matched_instructor_links_to_their_profile(monkeypatch):
    row, _, _ = instructor(monkeypatch)
    assert row["slug"] == "dan-koloski"
    assert row["imageUrl"] == "http://img/dk.jpg"
    assert row["totalReviews"] == 40


def test_rmp_numbers_are_read_under_the_rmp_spelling(monkeypatch):
    row, seen, _ = instructor(monkeypatch)
    assert "dan koloski" in seen["rmp_keys"]
    # RMP comments under "dan koloski" plus TRACE comments under "daniel koloski".
    assert row["totalComments"] == 8
    # TRACE difficulty 3.0 averaged with RMP's 1.0 for this course.
    assert row["courseAvgDifficulty"] == 2.0


def test_catalog_without_the_column_still_serves(monkeypatch):
    row, _, conn = instructor(monkeypatch, has_trace_column=False)
    assert row["slug"] == ""
    assert conn.rollbacks == 1
