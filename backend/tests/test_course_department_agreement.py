"""The department dropdown and the course list must agree, measured on real data.

/api/course-departments populates the Courses page filter, and the choice is
sent back as /api/courses-catalog?dept=. The two once derived a course's
department independently — the dropdown from catalog_courses, the filter from
course_catalog.department (TRACE's names) — and each passed its own unit test
while together they broke the page: on the 2026-27 catalog, 188 of 238 options
returned no courses and 2,265 of 5,199 rated courses sat under a name the
dropdown no longer offered. Fakes that match on SQL text cannot see that, so
this runs the real endpoints against a real database.

Read-only. Uses CATALOG_AGREEMENT_DSN when set (point it at a local throwaway
database), otherwise the live URL from backend/.env, and skips cleanly with
neither — the same contract as test_measured_claims.py.
"""

import os
import pathlib

import pytest

os.environ.setdefault("CRDB_DATABASE_URL", "postgresql://stub")
os.environ.setdefault("JWT_SECRET", "test-secret")

REPO = pathlib.Path(__file__).resolve().parents[2]


def _dsn():
    explicit = os.getenv("CATALOG_AGREEMENT_DSN")
    if explicit:
        return explicit
    try:
        from dotenv import dotenv_values
    except ImportError:
        return None
    return dotenv_values(REPO / "backend" / ".env").get("CRDB_DATABASE_URL")


@pytest.fixture(scope="module")
def conn():
    dsn = _dsn()
    if not dsn:
        pytest.skip("no database configured -- department agreement unverified")
    try:
        import psycopg2
        c = psycopg2.connect(dsn, sslmode="require", connect_timeout=15)
        c.autocommit = True
    except Exception as exc:                      # noqa: BLE001 - any failure skips
        pytest.skip(f"database unreachable -- department agreement unverified ({exc})")
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def client(conn, monkeypatch):
    import server

    monkeypatch.setattr(server, "get_db", lambda: conn)
    monkeypatch.setattr(server, "cache_get", lambda key: None)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None)
    # One request per department is a few hundred in a second — the 20/s
    # default limit would 429 the sweep, not the code under test.
    monkeypatch.setattr(server.limiter, "enabled", False)
    return server.app.test_client()


def _json(resp):
    assert resp.status_code == 200, (resp.status_code, resp.data[:200])
    return resp.get_json()


@pytest.fixture
def dropdown(client):
    return _json(client.get("/api/course-departments"))


@pytest.fixture
def all_courses(client):
    data = _json(client.get("/api/courses-catalog?limit=10000"))
    assert data["total"] == len(data["courses"]), "fixture must see every course"
    return data["courses"]


def test_every_dropdown_option_finds_courses(client, dropdown):
    dead = [d for d in dropdown
            if _json(client.get("/api/courses-catalog",
                                query_string={"dept": d, "limit": 1}))["total"] == 0]
    assert dead == [], f"{len(dead)} of {len(dropdown)} options return nothing: {dead[:8]}"


def test_every_course_is_reachable_by_department(dropdown, all_courses):
    offered = set(dropdown)
    stranded = [c["code"] for c in all_courses
                if c["department"] and c["department"] not in offered]
    assert stranded == [], f"{len(stranded)} courses under unlisted departments: {stranded[:8]}"


def test_filtering_returns_exactly_that_departments_courses(client, all_courses):
    by_dept = {}
    for c in all_courses:
        by_dept[c["department"]] = by_dept.get(c["department"], 0) + 1
    largest = sorted((d for d in by_dept if d), key=by_dept.get, reverse=True)[:5]
    for d in largest:
        got = _json(client.get("/api/courses-catalog", query_string={"dept": d, "limit": 10000}))
        assert got["total"] == by_dept[d], d
        assert {c["department"] for c in got["courses"]} == {d}


# ── the same contract on sqlite, so CI checks it without a database ─────────
#
# The live sweep above skips in CI. These run the endpoints' real SQL on an
# in-memory sqlite built to the same shape, so the agreement is checked on
# every push rather than only when someone points the sweep at a database.
# sqlite lacks regexp_extract, which is registered below with CockroachDB's
# semantics (first match, else NULL).

import re
import sqlite3

TRACE_ROWS = [  # (code, name, department) as precompute writes course_catalog
    ("SOCL1001", "Intro to Sociology", "Sociology and Anthropology"),
    ("ANTH1101", "Intro Cultural Anthropology", "Sociology and Anthropology"),
    ("CS3000", "Algorithms and Data", "Khoury"),
    ("AFAM1101", "Intro to Africana Studies", "African-American Studies"),
    ("LITR1101", "Intro to Literature", "Lang, Literature and Culture"),
]
CATALOG_ROWS = [  # (code, subject, department) as load_catalog_to_crdb writes them
    ("SOCL1001", "SOCL", "Sociology"),
    ("SOCL1002", "SOCL", "Sociology"),
    ("ANTH1101", "ANTH", "Anthropology"),
    ("CS3000", "CS", "Computer Science"),
    ("SOC1001", "SOC", "Sociology - CPS"),  # a subject with no TRACE course
]


def _regexp_extract(value, pattern):
    m = re.search(pattern, value or "")
    return m.group(0) if m else None


@pytest.fixture
def sqlite_client(monkeypatch):
    import server

    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.create_function("regexp_extract", 2, _regexp_extract)
    db.execute("""CREATE TABLE course_catalog (code TEXT PRIMARY KEY, name TEXT,
                  department TEXT, search_text TEXT, avg_rating REAL)""")
    db.executemany("INSERT INTO course_catalog VALUES (?, ?, ?, ?, NULL)",
                   [(c, n, d, f"{c.lower()} {n.lower()}") for c, n, d in TRACE_ROWS])
    db.execute("CREATE TABLE catalog_courses (code TEXT, subject TEXT, department TEXT)")
    db.executemany("INSERT INTO catalog_courses VALUES (?, ?, ?)", CATALOG_ROWS)
    # Committed, because the fallback paths call get_db().rollback() — which
    # on an open sqlite transaction would discard the fixture itself.
    db.commit()

    def run(sql, params=None):
        return [dict(r) for r in db.execute(sql.replace("%s", "?"), tuple(params or ()))]

    monkeypatch.setattr(server, "query", run)
    monkeypatch.setattr(server, "query_one", lambda sql, params=None: (run(sql, params) or [None])[0])
    monkeypatch.setattr(server, "get_db", lambda: db)
    monkeypatch.setattr(server, "cache_get", lambda key: None)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None)
    monkeypatch.setattr(server.limiter, "enabled", False)
    return server.app.test_client(), db


def _listed(client, **args):
    return {c["code"]: c["department"]
            for c in _json(client.get("/api/courses-catalog",
                                      query_string={"limit": 100, **args}))["courses"]}


def test_a_covered_subject_takes_the_catalog_department(sqlite_client):
    client, _ = sqlite_client
    listed = _listed(client)
    assert listed["SOCL1001"] == "Sociology"
    assert listed["ANTH1101"] == "Anthropology"


def test_a_retired_subject_keeps_its_trace_department(sqlite_client):
    client, _ = sqlite_client
    assert _listed(client)["AFAM1101"] == "African-American Studies"


def test_the_dropdown_is_exactly_the_departments_courses_carry(sqlite_client):
    client, _ = sqlite_client
    dropdown = _json(client.get("/api/course-departments"))
    assert dropdown == ["African-American Studies", "Anthropology",
                        "Computer Science", "Lang, Literature and Culture", "Sociology"]
    assert set(dropdown) == set(_listed(client).values())


def test_filtering_by_a_catalog_department_finds_its_courses(sqlite_client):
    client, _ = sqlite_client
    assert _listed(client, dept="Sociology") == {"SOCL1001": "Sociology"}
    assert _listed(client, dept="Anthropology|Computer Science") == {
        "ANTH1101": "Anthropology", "CS3000": "Computer Science"}


def test_a_department_name_containing_a_comma_is_one_department(sqlite_client):
    """The multi-select separator is "|" because real names carry commas —
    "Lang, Literature and Culture" in TRACE, "Women's, Gender, and Sexuality
    Studies" in the catalog. Split on "," and the name becomes two that match
    nothing."""
    client, _ = sqlite_client
    assert _listed(client, dept="Lang, Literature and Culture") == {
        "LITR1101": "Lang, Literature and Culture"}
    assert _listed(client, dept="Lang, Literature and Culture|Sociology") == {
        "LITR1101": "Lang, Literature and Culture", "SOCL1001": "Sociology"}


def test_the_superseded_trace_name_no_longer_matches(sqlite_client):
    client, _ = sqlite_client
    assert _listed(client, dept="Sociology and Anthropology") == {}


def test_a_missing_catalog_table_serves_trace_departments_on_both_endpoints(sqlite_client):
    client, db = sqlite_client
    db.execute("DROP TABLE catalog_courses")
    assert _json(client.get("/api/course-departments")) == [
        "African-American Studies", "Khoury", "Lang, Literature and Culture",
        "Sociology and Anthropology"]
    assert _listed(client, dept="Sociology and Anthropology") == {
        "SOCL1001": "Sociology and Anthropology", "ANTH1101": "Sociology and Anthropology"}
