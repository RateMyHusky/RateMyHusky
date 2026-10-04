"""Every route stays off 500 when the database holds only today's tables.

The fake database knows the tables the site runs on. A statement naming any
other table raises UndefinedTable, exactly what a dropped table produces, so a
route still reading a retired table fails here instead of in production.
Every other statement gets one row wide enough for any read the routes make:
this is a smoke test, and the assertion is only "no 5xx".
"""

import datetime
import os
import re

import jwt
import psycopg2.errors
import pytest

os.environ.setdefault("CRDB_DATABASE_URL", "postgresql://stub")
import server  # noqa: E402

LIVE_TABLES = {
    "professors_catalog", "course_catalog", "rmp_reviews", "rmp_professors",
    "stats_cache", "bookmarks", "reddit_mentions", "reddit_text", "reddit_sentiment",
    "ask_log", "evidence", "evidence_embeddings", "usage_alerts",
    "professors", "rmp_links", "source_summary", "catalog_courses", "catalog_nupath",
    "professor_tags",
}
_TABLE_REF = re.compile(r"\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)

ROW = {
    "slug": "olin-guha", "name": "Olin Guha", "name_key": "olin guha",
    "department": "Computer Science", "college": "Khoury", "avg_rating": 4.2,
    "rmp_rating": 4.2, "num_ratings": 12, "total_reviews": 12, "would_take_again_pct": 88.0,
    "difficulty": 3.1, "professor_url": None, "image_url": None, "focus_x": None,
    "focus_y": None, "total_comments": 3, "code": "CS3500", "search_text": "cs3500",
    "cnt": 1, "avg": 4.2, "prior": 4.2, "key": "professors", "value": 1,
    "course": "CS3500", "quality": 5, "date": "2024-01-01", "tags": "", "attendance": "",
    "grade": "A", "textbook": "", "online_class": "", "comment": "Great.", "rating": 4.2,
    "item_type": "professor", "item_key": "olin-guha",
    "tag": "curved_grading", "review_count": 3, "profs": 1,
    "created_at": datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc),
    "body": "text", "subreddit": "NEU", "permalink": "/r/x", "created_utc": None,
    "professor_slug": "olin-guha", "course_code": "CS3500", "source": "blend",
    "num_comments": 1, "hours_per_week": None, "rating_distribution": {}, "grade_distribution": {},
    "course_name": None, "description": None, "credit_hours": None, "prerequisites": None,
    "corequisites": None, "nupath": [],
    "reddit_score": 1, "sentiment": None, "sentiment_score": None, "source_id": "s1", "professor_slugs": ["olin-guha"], "score": 1,
}

TEST_SECRET = "test-secret-0123456789abcdefghijklmnop"  # gitleaks:allow
SAMPLE = {"slug": "olin-guha", "code": "CS3500"}
SKIP = {"/api/auth/google", "/api/auth/google/callback"}  # redirect to Google
EXTRA = ["/api/search?q=olin&type=Professor", "/api/search?q=cs&type=Course",
         "/api/professors-catalog?q=olin", "/api/courses-catalog?sort=rating",
         "/api/chat?q=olin", "/api/professors/nobody/full", "/api/courses/zz0000",
         "/render/professors/nobody", "/render/courses/zz0000"]


def fake_query(sql, params=()):
    for table in _TABLE_REF.findall(sql):
        if table.lower() not in LIVE_TABLES:
            raise psycopg2.errors.UndefinedTable(f'relation "{table}" does not exist')
    return [dict(ROW)]


def test_the_fake_rejects_a_table_that_is_not_live():
    with pytest.raises(psycopg2.errors.UndefinedTable):
        fake_query("SELECT 1 FROM retired_table")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "JWT_SECRET", TEST_SECRET, raising=False)
    monkeypatch.setattr(server, "_get_pool",
                        lambda: (_ for _ in ()).throw(AssertionError("no DB in test")), raising=False)
    monkeypatch.setattr(server, "cache_get", lambda key: None, raising=False)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None, raising=False)
    monkeypatch.setattr(server.limiter, "enabled", False)
    monkeypatch.setattr(server, "query", fake_query, raising=False)
    return server.app.test_client()


def _get_paths():
    paths = []
    for rule in server.app.url_map.iter_rules():
        if "GET" not in rule.methods or rule.rule.startswith("/static") or rule.rule in SKIP:
            continue
        paths.append(re.sub(r"<(?:\w+:)?(\w+)>", lambda m: SAMPLE[m.group(1)], rule.rule))
    return paths + EXTRA


def test_no_route_errors_on_the_live_tables(client):
    token = jwt.encode({"sub": "u1", "email": "t@husky.neu.edu", "name": "T",
                        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)},
                       TEST_SECRET, algorithm="HS256")
    failures = []
    for path in _get_paths():
        for headers in ({}, {"Authorization": f"Bearer {token}"}):
            resp = client.get(path, headers=headers)
            if resp.status_code >= 500:
                failures.append((path, bool(headers), resp.status_code, resp.get_data(as_text=True)[:200]))
    assert failures == []
