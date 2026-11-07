"""Flask endpoints, bookmarks and usage alerts through the real pool."""

import urllib.parse

import psycopg2.extras
import pytest

import bookmarks
import review_ratings
import usage_alert
from pipeline import read_models
from tests.pg.pgutil import truncate
from tests.pg.seed import CATALOG, COUNTS, COURSES, SUMMARIES


@pytest.fixture
def seeded(pg):
    truncate(pg, "professors_catalog", "course_catalog", "source_summary", "stats_cache")
    read_models.write(pg, CATALOG, COURSES, SUMMARIES, COUNTS)


@pytest.mark.parametrize("path", [
    "/api/stats",
    "/api/professors-catalog",
    "/api/courses-catalog",
    "/api/search?q=alice",
    "/api/professors/alice-smith/full",
    "/api/courses/CS2500",
])
def test_read_endpoints_return_200(live_server, seeded, path):
    # A 500 here is a real finding: read the traceback in the pytest output. A
    # KeyError/None on an empty table means a seed row is missing (add it to
    # tests/pg/seed.py); a psycopg2 error means SQL that PostgreSQL rejects (fix it).
    resp = live_server.app.test_client().get(path)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:500]


def test_bookmark_add_is_idempotent_and_remove_deletes(live_server, seeded, pg):
    truncate(pg, "bookmarks")
    with live_server.app.app_context():
        for _ in range(2):
            assert bookmarks.add_bookmark("user-1", "professor", "alice-smith",
                                          live_server.query_one, live_server._write) == "ok"
        saved = live_server.query("SELECT id FROM bookmarks WHERE user_sub = 'user-1'")
        assert len(saved) == 1 and saved[0]["id"] >= 1
        bookmarks.remove_bookmark("user-1", "professor", "alice-smith", live_server._write)
        assert live_server.query("SELECT 1 FROM bookmarks WHERE user_sub = 'user-1'") == []


def test_usage_alert_tier_is_claimed_once_per_utc_day(live_server, pg):
    truncate(pg, "usage_alerts")
    with live_server.app.app_context():
        assert usage_alert.claim_tier(live_server._chat_write_rc, 50) is True
        assert usage_alert.claim_tier(live_server._chat_write_rc, 50) is False
        row = live_server.query_one(
            "SELECT alert_date = (now() AT TIME ZONE 'UTC')::date AS utc_today "
            "FROM usage_alerts WHERE tier = 50")
    assert row["utc_today"] is True


def test_ask_log_purge_deletes_only_rows_past_retention(live_server, pg, monkeypatch):
    # _chat_write swallows SQL errors, so only the remaining rows show the DELETE ran.
    truncate(pg, "ask_log")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO ask_log (query, mode, result_status, created_at) VALUES "
                    "('old', 'question', 'ok', now() - interval '31 days'), "
                    "('new', 'question', 'ok', now() - interval '29 days')")
    pg.commit()
    monkeypatch.setitem(live_server._ask_log_purge, "last", 0.0)
    live_server._purge_ask_log_job()
    with pg.cursor() as cur:
        cur.execute("SELECT query FROM ask_log")
        assert [r[0] for r in cur.fetchall()] == ["new"]
    pg.commit()


def _course(code, name, search_text, num_ratings):
    return {"code": code, "name": name, "department": "Computer Science", "subject": "CS",
            "search_text": search_text, "avg_rating": 4.0, "difficulty": 3.0, "num_ratings": num_ratings}


@pytest.mark.parametrize("path, key", [
    ("/api/search?type=Course&q=cs%2035", "code"),
    ("/api/courses-catalog?q=cs%2035", "code"),
    ("/api/courses-catalog?q=cs%2035&sort=recent", "code"),   # joins banner_course_offerings when present
    ("/api/search?type=Course&q=calculus", "code"),
    ("/api/courses-catalog?q=calculus", "code"),
])
def test_course_search_ranks_code_and_title_matches_above_descriptions(live_server, pg, path, key):
    courses = [
        _course("CS3500", "Object-Oriented Design", "cs3500 cs 3500 object-oriented design", 10),
        # More rated, and its description names CS 3500 as a prerequisite.
        _course("CS4500", "Software Development", "cs4500 cs 4500 software development prereq cs 3500", 90),
        _course("MATH1341", "Calculus 1 for Science and Engineering", "math1341 math 1341 calculus 1", 20),
        _course("PHYS1151", "Physics for Engineering", "phys1151 phys 1151 physics uses calculus", 80),
    ]
    truncate(pg, "professors_catalog", "course_catalog", "source_summary", "stats_cache")
    read_models.write(pg, CATALOG, courses, SUMMARIES, COUNTS)
    resp = live_server.app.test_client().get(path, headers={"User-Agent": "Mozilla/5.0"})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:500]
    body = resp.get_json()
    rows = body["courses"] if isinstance(body, dict) else body
    assert rows[0][key] == ("CS3500" if "cs" in path else "MATH1341"), rows


@pytest.mark.parametrize("endpoint", ["/api/search?type=Course&q=", "/api/courses-catalog?q="])
@pytest.mark.parametrize("q, code", [
    ("object oriented", "CS3500"),
    ("object-oriented", "CS3500"),
    ("objectoriented", "CS3500"),
    ("study argentina", "ABRD5140"),
    ("bouve", "HSCI2000"),
    ("bouvé", "HSCI2000"),
    ("master’s", "CHME7945"),
    ("masters", "CHME7945"),
    ("c++", "CS3520"),
    ("c#", "CSYE6202"),
])
def test_course_search_folds_punctuation_spacing_and_accents(live_server, pg, endpoint, q, code):
    rows = [
        ("CS3500", "Object-Oriented Design", ""),
        ("CSYE7200", "Big Data Systems", "object oriented programming"),
        ("ABRD5140", "International Study—Argentina", ""),
        ("HSCI2000", "Co-op for Bouvé Students", ""),
        ("CHME7945", "Master’s Project", ""),
        ("CS3520", "Programming in C++", ""),
        ("CSYE6202", "Enterprise Software Design with C#", ""),
    ]
    courses = [_course(c, n, read_models.course_search_text(c, f"{c.lower()} {n.lower()} {d}"), 10)
               for c, n, d in rows]
    truncate(pg, "professors_catalog", "course_catalog", "source_summary", "stats_cache")
    read_models.write(pg, CATALOG, courses, SUMMARIES, COUNTS)
    resp = live_server.app.test_client().get(endpoint + urllib.parse.quote(q), headers={"User-Agent": "Mozilla/5.0"})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:500]
    body = resp.get_json()
    found = body["courses"] if isinstance(body, dict) else body
    assert found[0]["code"] == code, found


@pytest.mark.parametrize("q", ["bouve", "bouvé"])
def test_an_accented_title_ranks_above_a_description_match(live_server, pg, q):
    courses = [_course(c, n, read_models.course_search_text(c, f"{c.lower()} {n.lower()} {d}"), r)
               for c, n, d, r in [("HSCI2000", "Co-op for Bouvé Students", "", 1),
                                  ("HSCI1000", "College: An Introduction", "for bouve students", 50)]]
    truncate(pg, "professors_catalog", "course_catalog", "source_summary", "stats_cache")
    read_models.write(pg, CATALOG, courses, SUMMARIES, COUNTS)
    found = live_server.app.test_client().get("/api/search?type=Course&q=" + urllib.parse.quote(q),
                                              headers={"User-Agent": "Mozilla/5.0"}).get_json()
    assert [r["code"] for r in found] == ["HSCI2000", "HSCI1000"]


def test_courses_catalog_ignores_a_single_folded_character(live_server, seeded):
    # "x'" folds to "x", which CS2500's search text doesn't contain: no filter lists it.
    body = live_server.app.test_client().get("/api/courses-catalog?q=x%27",
                                             headers={"User-Agent": "Mozilla/5.0"}).get_json()
    assert [c["code"] for c in body["courses"]] == ["CS2500"]


@pytest.mark.parametrize("path", ["/api/search?type=Course&q=a%27", "/api/search?q=a%27"])
def test_search_of_a_single_folded_character_returns_nothing(live_server, seeded, path):
    resp = live_server.app.test_client().get(path, headers={"User-Agent": "Mozilla/5.0"})
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_course_search_with_an_empty_fold_returns_nothing(live_server, seeded):
    resp = live_server.app.test_client().get("/api/search?type=Course&q=%27%E2%80%94",
                                             headers={"User-Agent": "Mozilla/5.0"})
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_search_finds_an_approved_alias_only(live_server, seeded, pg):
    truncate(pg, "professor_aliases")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professor_aliases (alias_key, slug, source) "
                    "VALUES ('zork', 'alice-smith', 'comment')")
    pg.commit()
    client = live_server.app.test_client()

    live_server._reset_alias_cache()
    assert client.get("/api/search?q=zork").get_json() == []

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id FROM professor_aliases")
        review_ratings.approve_alias(cur, str(cur.fetchone()["id"]))
    pg.commit()
    live_server._reset_alias_cache()
    found = client.get("/api/search?q=zork")
    assert [r["slug"] for r in found.get_json()] == ["alice-smith"]
    assert "zork" not in found.get_data(as_text=True).lower()
    truncate(pg, "professor_aliases")


def test_an_alias_hit_survives_the_100_row_cut(live_server, seeded, pg):
    truncate(pg, "professor_aliases")
    with pg.cursor() as cur:
        for i in range(105):
            cur.execute("INSERT INTO professors_catalog (slug, name, name_key, total_reviews) "
                        "VALUES (%s, %s, %s, 50)", (f"zork-{i}", f"Azork Person{i}", f"azork person{i}"))
        cur.execute("INSERT INTO professor_aliases (alias_key, slug, status, source) "
                    "VALUES ('zork', 'alice-smith', 'approved', 'manual')")
    pg.commit()
    live_server._reset_alias_cache()
    found = live_server.app.test_client().get("/api/search?q=zork&limit=20").get_json()
    assert found[0]["slug"] == "alice-smith"
    truncate(pg, "professor_aliases", "professors_catalog")
    live_server._reset_alias_cache()


def test_catalog_pages_show_each_professor_once_when_sort_values_tie(live_server, pg, monkeypatch):
    # Tied rows have no fixed order in Postgres, so without a unique last sort key a LIMIT/OFFSET
    # page can repeat professors from an earlier page and skip others.
    monkeypatch.setattr(live_server.limiter, "enabled", False)  # the walk is ~50 requests in well under a second
    truncate(pg, "professors_catalog")
    slugs = [f"sam-lee-{i}" for i in range(60)]
    with pg.cursor() as cur:
        for i, slug in enumerate(slugs):
            cur.execute("INSERT INTO professors_catalog (slug, name, name_key, total_reviews, avg_rating, total_comments) "
                        "VALUES (%s, 'Sam Lee', %s, 10, 4.0, 5)", (slug, f"sam lee {i}"))
    pg.commit()
    client = live_server.app.test_client()
    # A search (q) ranks instead of sorting, and every match ties on its rank and review count.
    for query in [f"sort={sort}" for sort in sorted(live_server.PROFESSOR_SORTS)] + ["q=sam+lee"]:
        seen, page, pages = [], 1, 1
        while page <= pages:
            body = client.get(f"/api/professors-catalog?{query}&page={page}&limit=7").get_json()
            seen += [p["slug"] for p in body["professors"]]
            pages = body["totalPages"]
            page += 1
        assert sorted(seen) == sorted(slugs), query
    truncate(pg, "professors_catalog")


def test_catalog_rating_sorts_weight_by_number_of_ratings(live_server, pg):
    # Prior = mean of rows with >= 30 reviews = (4.8 + 2.0) / 2 = 3.4. With m = 50:
    # many-high 4.52, one-five 3.43, one-one 3.35, many-low 2.28.
    truncate(pg, "professors_catalog")
    rows = [("many-high", 4.8, 200), ("one-five", 5.0, 1), ("one-one", 1.0, 1), ("many-low", 2.0, 200)]
    with pg.cursor() as cur:
        for slug, avg, n in rows:
            cur.execute("INSERT INTO professors_catalog (slug, name, name_key, total_reviews, avg_rating, total_comments) "
                        "VALUES (%s, %s, %s, %s, %s, 0)", (slug, slug, slug.replace("-", " "), n, avg))
    pg.commit()
    client = live_server.app.test_client()
    order = lambda sort: [p["slug"] for p in client.get(f"/api/professors-catalog?sort={sort}&limit=10").get_json()["professors"]]
    assert order("rating") == ["many-high", "one-five", "one-one", "many-low"]
    assert order("rating_asc") == ["many-low", "one-one", "one-five", "many-high"]
    truncate(pg, "professors_catalog")


@pytest.mark.parametrize("q, slug", [
    ("obrien", "david-o-brien"),
    ("o’brien", "david-o-brien"),
    ("O’BRIEN", "david-o-brien"),
    ("o brien", "david-o-brien"),
    ("o'brien", "david-o-brien"),
    ("nunez neto", "blas-nunez-neto"),
    ("nunezneto", "blas-nunez-neto"),
    ("dominguez", "carlos-dominguez"),
    ("domínguez", "carlos-dominguez"),
])
def test_professor_search_ignores_apostrophes_hyphens_and_accents(live_server, pg, q, slug):
    rows = [
        dict(CATALOG[0], slug="david-o-brien", name="David O'Brien", name_key="david o'brien"),
        dict(CATALOG[0], slug="blas-nunez-neto", name="Blas Nunez-Neto", name_key="blas nunez-neto"),
        dict(CATALOG[0], slug="carlos-dominguez", name="Carlos Domínguez", name_key="carlos dominguez"),
    ]
    truncate(pg, "professors_catalog", "course_catalog", "source_summary", "stats_cache")
    read_models.write(pg, rows, COURSES, SUMMARIES, COUNTS)
    client = live_server.app.test_client()
    found = client.get("/api/search?q=" + urllib.parse.quote(q))
    assert found.status_code == 200, found.get_data(as_text=True)[:500]
    assert found.get_json()[0]["slug"] == slug
    assert client.get("/api/search?q=%27%27").get_json() == []
