import os

import pytest

# Test modules pin the JWT secret with os.environ.setdefault("JWT_SECRET",
# "test-secret"), which silently loses whenever a real value is already in the
# environment — and importing server or precompute calls load_dotenv(), which
# injects the developer's real .env. Whether the suite passed then came down to
# alphabetical collection order: if a module calling load_dotenv() sorted before
# the module doing the setdefault, every token signed with "test-secret" failed
# to validate and the auth-gated tests 401'd. conftest is imported before any
# test module, so pinning it here makes the suite order- and .env-independent.
# load_dotenv() does not override existing vars, so this value survives.
os.environ["JWT_SECRET"] = "test-secret"

# migrate_to_crdb reads the DB URL at import and sys.exits when it is missing,
# so importing it for a pure-logic test (REPLACE_ALLOWED, TABLES) takes the whole
# collection down wherever backend/.env is absent — which is every CI run, since
# ci.yml only checks the repo out. Set here rather than in the test modules for
# the same reason JWT_SECRET is: conftest is imported first, and load_dotenv()
# does not override an existing var. A deliberately unusable value — nothing in
# the suite connects, and a real URL here would let a stray test reach prod.
os.environ["CRDB_DATABASE_URL"] = "postgresql://test:test@localhost:26257/test"
# pipeline.db prefers this name, and load_dotenv() would inject the real one.
os.environ["NEW_CRDB_DATABASE_URL"] = "postgresql://test:test@localhost:26257/test"


@pytest.fixture
def render_client(monkeypatch):
    """A Flask test client for the render blueprint with the server's data
    view functions stubbed, so no DB is needed."""
    import render

    # Stubs returning Flask-like JSON via a tiny fake response object.
    class FakeResp:
        def __init__(self, data, status=200):
            self._data = data
            self.status_code = status
        def get_json(self):
            return self._data

    def fake_professor_payload(slug):
        if slug == "missing":
            return None
        return {
            "version": 2,
            "identity": {"slug": "francis-georges", "name": "Francis Georges",
                         "department": "Economics", "college": "CSSH",
                         "imageUrl": None, "focusX": 50.0, "focusY": 30.0},
            "summary": {"rating": 4.25, "difficulty": 2.9, "wouldTakeAgainPct": 83,
                        "numRatings": 2686, "numComments": 1, "hoursPerWeek": None,
                        "bySource": {"rmp": {"rating": 4.25, "numRatings": 2686}}},
            "sources": {"rmp": {
                "available": True, "rating": 4.25, "difficulty": 2.9, "wouldTakeAgainPct": 83,
                "numRatings": 2686, "professorUrl": None,
                "ratingDistribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 1},
                "gradeDistribution": {},
                "reviews": [{"course": "ECON1115", "quality": 5, "difficulty": 3,
                             "date": "2024", "comment": "Excellent lecturer."}]}},
            "courses": [{"code": "ECON1115", "name": "Macroeconomics", "rating": 5.0,
                         "difficulty": 3.0, "numRatings": 1,
                         "ratingDistribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 1}}],
            "redditMentions": [],
        }

    def fake_colleagues(department, exclude_slug):
        return [{"name": "Alice Smith", "slug": "alice-smith", "avgRating": 4.5, "totalRatings": 30}]

    def fake_course_payload(code):
        if code == "missing":
            return None
        return {
            "code": "ECON1115", "name": "Macroeconomics", "department": "Economics",
            "catalog": {"description": "Covers the macroeconomy.", "credits": "4",
                        "prerequisites": "ECON 1116 with a minimum grade of D-", "corequisites": None,
                        "nupath": ["Analyzing/Using Data", "Societies/Institutions"]},
            "summary": {"rating": 4.1, "difficulty": 2.5, "numRatings": 342, "hoursPerWeek": None,
                        "bySource": {"rmp": {"rating": 4.1, "numRatings": 342}}},
            "professors": [{"slug": "francis-georges", "name": "Francis Georges", "imageUrl": None,
                            "focusX": 50.0, "focusY": 30.0, "rating": 4.1, "difficulty": 2.5,
                            "numRatings": 342}],
        }

    def fake_stats():
        return FakeResp([
            {"label": "Professors", "value": "9.3K"},
            {"label": "Courses", "value": "5K"},
            {"label": "Comments", "value": "120K"},
            {"label": "Departments", "value": "180"},
        ])

    def fake_professors_catalog():
        return FakeResp({"professors": [
            {"name": "Francis Georges", "slug": "francis-georges",
             "department": "Economics", "avgRating": 4.25},
        ], "total": 9329, "page": 1, "totalPages": 466})

    def fake_courses_catalog():
        return FakeResp({"courses": [
            {"code": "ECON1115", "name": "Macroeconomics",
             "department": "Economics", "avgRating": 4.1},
        ], "total": 5013, "page": 1, "totalPages": 251})

    def fake_departments_hub():
        return FakeResp({"departments": [
            {"slug": "computer-science", "name": "Computer Science",
             "professorCount": 214, "avgRating": 3.9},
        ], "total": 80})

    def fake_department_hub_detail(slug):
        if slug == "missing":
            return ({"error": "not found"}, 404)
        return FakeResp({
            "name": "Computer Science", "slug": "computer-science",
            "professorCount": 1, "avgRating": 4.25,
            "professors": [
                {"name": "Francis Georges", "slug": "francis-georges",
                 "avgRating": 4.25, "difficulty": 2.9,
                 "wouldTakeAgainPct": 83, "totalRatings": 2686},
            ],
        })

    monkeypatch.setattr(render, "_get_professor_payload", lambda: fake_professor_payload, raising=False)
    monkeypatch.setattr(render, "_get_colleagues", lambda: fake_colleagues, raising=False)
    monkeypatch.setattr(render, "_get_course_payload", lambda: fake_course_payload, raising=False)
    monkeypatch.setattr(render, "_get_stats_view", lambda: fake_stats, raising=False)
    monkeypatch.setattr(render, "_get_professors_catalog_view", lambda: fake_professors_catalog, raising=False)
    monkeypatch.setattr(render, "_get_courses_catalog_view", lambda: fake_courses_catalog, raising=False)
    monkeypatch.setattr(render, "_get_departments_hub_view", lambda: fake_departments_hub, raising=False)
    monkeypatch.setattr(render, "_get_department_hub_detail_view", lambda: fake_department_hub_detail, raising=False)

    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(render.render_bp)
    return app.test_client()
