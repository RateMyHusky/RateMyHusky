
import os

import pytest

os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")

import server


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server.limiter, "enabled", False)

    def fake_query(sql, params=None):
        assert "banner_sections" in sql
        assert params[0] == "202730"

        return [
            {
                "crn": "36973",
                "instructor_key": "rachlin john",
                "instructor_name": "Rachlin, John",
                "is_primary": True,
                "professor_slug": "john-rachlin",
                "rating": 4.63,
                "num_ratings": 52,
                "ambiguous": False,
            },
            {
                "crn": "31896",
                "instructor_key": "van julie",
                "instructor_name": "Van, Julie",
                "is_primary": True,
                "professor_slug": None,
                "rating": None,
                "num_ratings": None,
                "ambiguous": False,
            },
        ]

    monkeypatch.setattr(server, "query", fake_query)
    return server.app.test_client()


def test_banner_sections_returns_ratings(client):
    response = client.get(
        "/api/banner/sections?term=202730&crns=31896,36973"
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["36973"] == {
        "instructor": "Rachlin, John",
        "slug": "john-rachlin",
        "rating": 4.63,
        "numRatings": 52,
    }

    assert data["31896"]["instructor"] == "Van, Julie"
    assert data["31896"]["slug"] is None
    assert data["31896"]["rating"] is None


@pytest.mark.parametrize("url", [
    "/api/banner/sections?term=abc&crns=31896",
    "/api/banner/sections?term=202730&crns=",
    "/api/banner/sections?term=202730&crns=hello",
])
def test_banner_sections_rejects_invalid_input(client, url):
    response = client.get(url)
    assert response.status_code == 400

def test_ambiguous_instructor_has_no_rating(client, monkeypatch):
    def fake_query(sql, params=None):
        return [{
            "crn": "36973",
            "instructor_key": "john rachlin",
            "instructor_name": "Rachlin, John",
            "is_primary": True,
            "professor_slug": "john-rachlin",
            "rating": 4.63,
            "num_ratings": 52,
            "ambiguous": True,
        }]

    monkeypatch.setattr(server, "query", fake_query)

    response = client.get(
        "/api/banner/sections?term=202730&crns=36973"
    )

    assert response.status_code == 200

    result = response.get_json()["36973"]

    assert result["instructor"] == "Rachlin, John"
    assert result["slug"] is None
    assert result["rating"] is None
    assert result["numRatings"] == 0

def test_conflicting_professor_matches_return_no_rating(client, monkeypatch):
    def fake_query(sql, params=None):
        return [
            {
                "crn": "36973",
                "instructor_key": "rachlin john",
                "instructor_name": "Rachlin, John",
                "is_primary": True,
                "professor_slug": "john-rachlin",
                "rating": 4.63,
                "num_ratings": 52,
                "ambiguous": False,
            },
            {
                "crn": "36973",
                "instructor_key": "rachlin john",
                "instructor_name": "Rachlin, John",
                "is_primary": True,
                "professor_slug": "different-professor",
                "rating": 3.50,
                "num_ratings": 20,
                "ambiguous": False,
            },
        ]

    monkeypatch.setattr(server, "query", fake_query)

    response = client.get(
        "/api/banner/sections?term=202730&crns=36973"
    )

    assert response.status_code == 200
    result = response.get_json()["36973"]

    assert result["instructor"] == "Rachlin, John"
    assert result["slug"] is None
    assert result["rating"] is None
    assert result["numRatings"] == 0
