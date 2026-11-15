
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
    response = client.post(
        "/api/banner/sections",
        json={"term": "202730", "crns": ["31896", "36973"]},
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


@pytest.mark.parametrize("body", [
    {"term": "abc", "crns": ["31896"]},
    {"term": "202730", "crns": []},
    {"term": "202730", "crns": ["hello"]},
    {"term": "202730", "crns": [31896]},
    {"term": "202730", "crns": "31896"},
    {"term": "202730", "crns": [str(10000 + i) for i in range(51)]},
    ["202730", ["31896"]],
])
def test_banner_sections_rejects_invalid_input(client, body):
    response = client.post("/api/banner/sections", json=body)
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

    response = client.post(
        "/api/banner/sections",
        json={"term": "202730", "crns": ["36973"]},
    )

    assert response.status_code == 200

    result = response.get_json()["36973"]

    assert result["instructor"] == "Rachlin, John"
    assert result["slug"] is None
    assert result["rating"] is None
    assert result["numRatings"] == 0

def test_instructor_name_is_unescaped(client, monkeypatch):
    def fake_query(sql, params=None):
        return [{
            "crn": "30351",
            "instructor_key": "o'connell sean",
            "instructor_name": "O&#39;Connell, Se&aacute;n",
            "is_primary": True,
            "professor_slug": "sean-oconnell",
            "rating": 4.1,
            "num_ratings": 9,
            "ambiguous": False,
        }]

    monkeypatch.setattr(server, "query", fake_query)

    response = client.post(
        "/api/banner/sections",
        json={"term": "202730", "crns": ["30351"]},
    )

    assert response.status_code == 200
    assert response.get_json()["30351"]["instructor"] == "O'Connell, Seán"

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

    response = client.post(
        "/api/banner/sections",
        json={"term": "202730", "crns": ["36973"]},
    )

    assert response.status_code == 200
    result = response.get_json()["36973"]

    assert result["instructor"] == "Rachlin, John"
    assert result["slug"] is None
    assert result["rating"] is None
    assert result["numRatings"] == 0


def test_banner_sections_accepts_fifty_crns(client):
    response = client.post(
        "/api/banner/sections",
        json={"term": "202730", "crns": [str(10000 + i) for i in range(50)]},
    )
    assert response.status_code == 200


def test_banner_sections_is_post_only(client):
    """CRNs in a query string end up in request logs."""
    response = client.get("/api/banner/sections?term=202730&crns=36973")
    assert response.status_code == 405


def test_co_taught_without_unique_primary_names_nobody(client, monkeypatch):
    """The extension reads `instructor` as one Banner name. A joined "A / B"
    failed its stale check or showed A alone as unrated, so it's null."""
    def fake_query(sql, params=None):
        base = {"crn": "10003", "professor_slug": None, "rating": None,
                "num_ratings": None, "ambiguous": False, "is_primary": False}
        return [
            {**base, "instructor_key": "rachlin john", "instructor_name": "Rachlin, John"},
            {**base, "instructor_key": "smith jane", "instructor_name": "Smith, Jane"},
        ]

    monkeypatch.setattr(server, "query", fake_query)
    response = client.post("/api/banner/sections", json={"term": "202730", "crns": ["10003"]})

    assert response.get_json()["10003"] == {
        "instructor": None, "slug": None, "rating": None, "numRatings": 0,
    }


def test_lookup_counts_blended_reviews_and_reads_banner_rows_only(client, monkeypatch):
    """avg_rating is blended, so the count beside it must be too, and the
    one-off 'import' instructor rows are no basis for a rating."""
    seen = {}

    def fake_query(sql, params=None):
        seen["sql"] = " ".join(sql.split())
        return []

    monkeypatch.setattr(server, "query", fake_query)
    client.post("/api/banner/sections", json={"term": "202730", "crns": ["36973"]})

    assert "pc.total_reviews AS num_ratings" in seen["sql"]
    assert "bsi.source = 'banner'" in seen["sql"]
