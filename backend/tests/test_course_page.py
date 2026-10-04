"""The course page payload (/api/courses/<code>, spec §4.3)."""

import os

import pytest

os.environ.setdefault("CRDB_DATABASE_URL", "postgresql://stub")
import server  # noqa: E402
from course_page import build_course  # noqa: E402

COURSE = {"code": "CS3500", "name": "Object-Oriented Design", "department": "Computer Science",
          "description": "Design.", "credit_hours": "4", "prerequisites": "CS2510", "corequisites": None,
          "nupath": ["NUpath Analyzing/Using Data"]}
_NONE = {"rating": None, "difficulty": None, "hours_per_week": None, "image_url": None,
         "focus_x": None, "focus_y": None, "name": None}
ROWS = [
    {**_NONE, "professor_slug": "", "source": "blend", "rating": 4.25, "difficulty": 3.25, "num_ratings": 40,
     "hours_per_week": 6.5},
    {**_NONE, "professor_slug": "", "source": "rmp", "rating": 4.25, "difficulty": 3.25, "num_ratings": 40},
    {**_NONE, "professor_slug": "olin-guha", "source": "blend", "rating": 4.5, "difficulty": 3.0,
     "num_ratings": 30, "name": "Olin Guha"},
    {**_NONE, "professor_slug": "amal-ahmed", "source": "blend", "rating": 3.5, "difficulty": 4.0,
     "num_ratings": 10, "name": "Amal Ahmed", "image_url": "https://img/a.jpg", "focus_x": 40.0,
     "focus_y": 20.0},
]


class FakeDB:
    def __init__(self, course=COURSE, rows=ROWS):
        self.course, self.rows, self.calls = course, rows, []

    def query(self, sql, params=None):
        self.calls.append(sql)
        assert "FROM source_summary" in sql
        return [dict(r) for r in self.rows]

    def query_one(self, sql, params=None):
        self.calls.append(sql)
        assert "FROM course_catalog" in sql
        return dict(self.course) if self.course and params[0] == self.course["code"] else None


def test_contract_keys():
    data = build_course("CS3500", FakeDB().query, FakeDB().query_one)
    assert set(data) == {"code", "name", "department", "catalog", "summary", "professors"}
    assert set(data["catalog"]) == {"description", "credits", "prerequisites", "corequisites", "nupath"}
    assert set(data["summary"]) == {"rating", "difficulty", "numRatings", "hoursPerWeek", "bySource"}
    assert all(set(p) == {"slug", "name", "imageUrl", "focusX", "focusY", "rating", "difficulty",
                          "numRatings"} for p in data["professors"])


def test_catalog_details_come_from_the_course_row():
    db = FakeDB()
    assert build_course("CS3500", db.query, db.query_one)["catalog"] == {
        "description": "Design.", "credits": "4", "prerequisites": "CS2510", "corequisites": None,
        "nupath": ["NUpath Analyzing/Using Data"]}


def test_summary_comes_from_the_course_blend_row():
    db = FakeDB()
    data = build_course("CS3500", db.query, db.query_one)
    assert data["summary"] == {"rating": 4.25, "difficulty": 3.25, "numRatings": 40,
                               "hoursPerWeek": 6.5,
                               "bySource": {"rmp": {"rating": 4.25, "numRatings": 40}}}


def test_professor_rows_default_the_photo_focus():
    db = FakeDB()
    p = build_course("CS3500", db.query, db.query_one)["professors"][0]
    assert p == {"slug": "olin-guha", "name": "Olin Guha", "imageUrl": None, "focusX": 50.0,
                 "focusY": 30.0, "rating": 4.5, "difficulty": 3.0, "numRatings": 30}


def test_professor_missing_from_the_catalog_is_left_out():
    rows = [*ROWS, {**_NONE, "professor_slug": "gone", "source": "blend", "rating": 5.0,
                    "difficulty": 1.0, "num_ratings": 99}]
    db = FakeDB(rows=rows)
    data = build_course("CS3500", db.query, db.query_one)
    assert [p["slug"] for p in data["professors"]] == ["olin-guha", "amal-ahmed"]


def test_course_without_reviews_is_200_with_nulls():
    db = FakeDB(rows=[])
    data = build_course("CS3500", db.query, db.query_one)
    assert data["summary"]["rating"] is None and data["summary"]["difficulty"] is None
    assert data["summary"]["numRatings"] == 0
    assert data["professors"] == []


def test_unknown_code_is_none():
    db = FakeDB()
    assert build_course("ZZZZ9999", db.query, db.query_one) is None


def test_two_statements():
    db = FakeDB()
    build_course("CS3500", db.query, db.query_one)
    assert len(db.calls) == 2


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(server, "_get_pool",
                        lambda: (_ for _ in ()).throw(AssertionError("no DB in test")), raising=False)
    monkeypatch.setattr(server, "cache_get", lambda key: None, raising=False)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None, raising=False)
    monkeypatch.setattr(server.limiter, "enabled", False)
    monkeypatch.setattr(server, "query", db.query, raising=False)
    monkeypatch.setattr(server, "query_one", db.query_one, raising=False)
    return server.app.test_client()


def test_route_serves_the_contract_case_insensitively(client):
    resp = client.get("/api/courses/cs3500")
    assert resp.status_code == 200
    assert resp.get_json()["code"] == "CS3500"
    assert "Authorization" in [t.strip() for t in resp.headers["Vary"].split(",")]


def test_route_404s_only_for_codes_outside_the_catalog(client):
    resp = client.get("/api/courses/zzzz9999")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "Course not found"}


def test_courses_catalog_sends_no_rating_filter_unless_asked(monkeypatch):
    seen = []
    monkeypatch.setattr(server, "cache_get", lambda key: None, raising=False)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None, raising=False)
    monkeypatch.setattr(server.limiter, "enabled", False)
    monkeypatch.setattr(server, "query_one", lambda sql, p=(): seen.append(sql) or {"cnt": 1}, raising=False)
    monkeypatch.setattr(server, "query", lambda sql, p=(): seen.append(sql) or [
        {"code": "CS3500", "name": "OOD", "department": "CS", "avg_rating": None}], raising=False)
    resp = server.app.test_client().get("/api/courses-catalog?sort=rating")
    assert resp.status_code == 200
    assert resp.get_json()["courses"][0]["avgRating"] is None
    assert not any("avg_rating >=" in s for s in seen)
    assert any("avg_rating DESC NULLS LAST, lower(code) ASC" in s for s in seen)
