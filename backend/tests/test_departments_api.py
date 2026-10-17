import os
import pytest


@pytest.fixture
def dept_client(monkeypatch):
    os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
    os.environ.setdefault("JWT_SECRET", "test-secret")
    import server
    # Stop the real pool from ever opening a connection during this test.
    monkeypatch.setattr(server, "_get_pool", lambda: (_ for _ in ()).throw(AssertionError("no DB in test")), raising=False)
    monkeypatch.setattr(server, "cache_get", lambda key: None, raising=False)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None, raising=False)

    def fake_query(sql, params=()):
        if "GROUP BY department" in sql:
            return [
                {"department": "Computer Science", "cnt": 3, "avg": 4.2},
                {"department": "Economics", "cnt": 1, "avg": 4.25},
            ]
        if "WHERE department = %s" in sql:
            dept = params[0]
            if dept == "Computer Science":
                return [
                    {"name": "Alice Smith", "slug": "alice-smith", "avg_rating": 4.5,
                     "difficulty": 2.1, "would_take_again_pct": 90.0, "total_reviews": 120},
                    {"name": "Bob Jones", "slug": "bob-jones", "avg_rating": 3.8,
                     "difficulty": 3.0, "would_take_again_pct": 70.0, "total_reviews": 45},
                    {"name": "Carol Lee", "slug": "carol-lee", "avg_rating": 3.3,
                     "difficulty": 4.2, "would_take_again_pct": None, "total_reviews": 10},
                ]
            return []
        raise AssertionError(f"unexpected query: {sql}")

    monkeypatch.setattr(server, "query", fake_query, raising=False)
    return server.app.test_client()


def test_departments_hub_list_shape_and_sort_order(dept_client):
    resp = dept_client.get("/api/departments/hub")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 2
    # sorted by professorCount desc
    assert [d["slug"] for d in data["departments"]] == ["computer-science", "economics"]
    cs = data["departments"][0]
    assert cs["name"] == "Computer Science"
    assert cs["professorCount"] == 3
    assert cs["avgRating"] == 4.2


def test_department_hub_detail_shape_all_professors_sorted_by_rating_desc(dept_client):
    resp = dept_client.get("/api/departments/computer-science")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "Computer Science"
    assert data["slug"] == "computer-science"
    assert data["professorCount"] == 3
    assert data["avgRating"] == 4.2
    assert [p["name"] for p in data["professors"]] == ["Alice Smith", "Bob Jones", "Carol Lee"]
    alice = data["professors"][0]
    assert alice == {
        "name": "Alice Smith", "slug": "alice-smith", "avgRating": 4.5,
        "difficulty": 2.1, "wouldTakeAgainPct": 90.0, "totalRatings": 120,
    }


def test_department_hub_detail_unknown_slug_is_404(dept_client):
    resp = dept_client.get("/api/departments/not-a-real-department")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "Department not found"}


def test_department_slug_is_deterministic_lowercase_and_ampersand():
    from server import department_slug
    assert department_slug("Computer Science") == "computer-science"
    assert department_slug("Counseling & Educational Psych") == "counseling-and-educational-psych"
    assert department_slug("Civil & Environmental Eng") == "civil-and-environmental-eng"


def test_department_slug_collapses_non_alphanumeric_runs_and_trims():
    from server import department_slug
    assert department_slug("  Art, Media & Design!!  ") == "art-media-and-design"
    assert department_slug("Bio/Chem--Eng") == "bio-chem-eng"
    assert department_slug("100% Physics") == "100-physics"


def test_department_slug_is_stable_across_repeated_calls():
    from server import department_slug
    name = "Electrical & Computer Engr"
    assert department_slug(name) == department_slug(name) == "electrical-and-computer-engr"
