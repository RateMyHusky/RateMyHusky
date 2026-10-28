"""Comment moderation against real PostgreSQL: the migration, the submit's check
fields, the retry queue, and what review_ratings.py list and the digest count.
Groq is always the FakeGroq in tests/conftest.py."""

import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from psycopg2.extras import RealDictCursor

import moderate_queue
import ratings
import review_digest
import review_ratings
from pipeline import read_models
from tests.pg.conftest import REPO
from tests.pg.pgutil import rows, scalar, truncate
from tests.pg.seed import CATALOG, COUNTS, COURSES, SUMMARIES

SECRET = "rating-secret-0123456789abcdefghijklmnop"  # gitleaks:allow
NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def clean(pg):
    truncate(pg, "survey_ratings", "moderation_calls", "survey_pending_professors", "survey_pending_courses")


def insert(pg, comment="A fair class with clear lectures.", device="d1", course="CS2500", **cols):
    row = {"id": str(uuid.uuid4()), "professor_slug": "alice-smith", "course_code": course, "rating": 4,
           "hours": "3-4", "status": "accepted", "device_hash": device, "new_device": True,
           "network_type": "other", "comment": comment, "comment_status": "pending" if comment else None,
           "comment_check": "unchecked" if comment else None, **cols}
    with pg.cursor() as cur:
        cur.execute(f"INSERT INTO survey_ratings ({', '.join(row)}) VALUES ({', '.join(['%s'] * len(row))})",
                    tuple(row.values()))
    pg.commit()
    return row["id"]


def get(pg, rating_id):
    (row,) = rows(pg, "SELECT * FROM survey_ratings WHERE id = %s", (rating_id,))
    return row


# ── migration ──

def _migration_sql():
    readme = (REPO / "db" / "postgres" / "README.md").read_text(encoding="utf-8")
    section = readme.split("Comments are then checked by a model", 1)[1]
    return re.search(r"```sql\n(.*?)```", section, re.S).group(1)


def test_the_migration_upgrades_a_191_table_and_reruns(pg):
    cur = pg.cursor()
    try:
        # Back to #191's shape inside this transaction, rolled back at the end.
        cur.execute("DROP TABLE moderation_calls")
        cur.execute("DROP INDEX survey_ratings_check_due")
        for column in ratings.CHECK_COLUMNS:
            cur.execute(f"ALTER TABLE survey_ratings DROP COLUMN {column}")
        cur.execute("INSERT INTO survey_ratings (id, professor_slug, course_code, rating, hours, status, "
                    "device_hash, new_device, network_type, comment, comment_status) VALUES "
                    "(gen_random_uuid(), 'alice-smith', 'CS2500', 4, '3-4', 'accepted', 'd1', true, 'other', "
                    "'Good class.', 'pending'), "
                    "(gen_random_uuid(), 'alice-smith', 'CS3500', 4, '3-4', 'accepted', 'd1', true, 'other', "
                    "NULL, NULL)")
        for _ in range(2):
            cur.execute(_migration_sql())
        cur.execute("SELECT comment IS NOT NULL AS has_comment, comment_check, comment_check_attempts, "
                    "comment_next_check_at FROM survey_ratings ORDER BY course_code")
        assert cur.fetchall() == [(True, "unchecked", 0, None), (False, None, None, None)]
        cur.execute("SELECT count(*) FROM moderation_calls")
        assert cur.fetchone() == (0,)
    finally:
        pg.rollback()


def test_the_schema_checks_the_new_values(pg):
    import psycopg2
    with pytest.raises(psycopg2.errors.CheckViolation):
        insert(pg, comment_check="block")
    pg.rollback()
    with pytest.raises(psycopg2.errors.CheckViolation), pg.cursor() as cur:
        cur.execute("INSERT INTO moderation_calls (id, source, outcome) VALUES (gen_random_uuid(), 'cron', 'allow')")
    pg.rollback()


# ── the upsert ──

def _save(pg, comment, check):
    def write(sql, params):
        with pg.cursor() as cur:
            cur.execute(sql, params)
        pg.commit()
    row = {c: None for c in ratings.RATING_COLUMNS if c != "id"}
    row.update(professor_slug="alice-smith", course_code="CS2500", rating=3, hours="3-4", status="accepted",
               device_hash="d1", new_device=True, network_type="other", collection="turnstile+device",
               comment=comment, **check)
    ratings.save_rating(row, None, write)


def test_an_edit_keeps_the_check_while_the_text_stays(pg):
    rating_id = insert(pg, comment_check="review", comment_check_reason="review", comment_check_attempts=1,
                       comment_checked_at=NOW)
    _save(pg, "A fair class with clear lectures.", {})
    kept = get(pg, rating_id)
    assert (kept["comment_check"], kept["comment_check_reason"], kept["rating"]) == ("review", "review", 3)
    _save(pg, "Changed my mind about it.",
          {"comment_check": "unchecked", "comment_check_reason": "over_budget", "comment_check_attempts": 0,
           "comment_next_check_at": NOW})
    reset = get(pg, rating_id)
    assert (reset["comment_check"], reset["comment_check_reason"], reset["comment_checked_at"]) == (
        "unchecked", "over_budget", None)
    _save(pg, None, {})
    assert all(get(pg, rating_id)[c] is None for c in ratings.CHECK_COLUMNS)


# ── submit through the real pool ──

@pytest.fixture
def submit(live_server, pg, monkeypatch, fake_groq):
    truncate(pg, "professors_catalog", "course_catalog", "source_summary", "stats_cache")
    read_models.write(pg, CATALOG, COURSES, SUMMARIES, COUNTS)
    import rating_identity as ri
    server = live_server
    monkeypatch.setattr(server, "RATING_SECRET", SECRET)
    monkeypatch.setattr(server, "PROXY_SECRET", None)
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.setattr(server, "_networks", SimpleNamespace(network_type=lambda ip: "other"))
    monkeypatch.setenv("GROQ_MODERATION_KEY", "gsk-test")
    # The seed has no one teaching CS2500; unverified_pair holds aren't what's tested here.
    monkeypatch.setattr(server.ratings, "pair_taught", lambda *a: True)
    server.limiter.reset()

    def post(reply, device, comment="Clear lectures and fair exams, would take again."):
        monkeypatch.setattr(server, "_groq_moderation_client", fake_groq(reply))
        opened = ri.sign_opened(SECRET, int(time.time()) - 60, ri.keyed_hash(SECRET, "device", device), False)
        client = server.app.test_client()
        client.set_cookie("rmh_device", device, path="/api")
        return client.post("/api/rate", json={
            "professor": {"slug": "alice-smith"}, "course": {"code": "CS2500"}, "term": "Fall 2025",
            "rating": 4, "difficulty": 3, "hours": "5-7", "grade": "A", "comment": comment,
            "opened": opened})
    return post, ri


def test_submit_stores_each_check_result(submit, pg, fake_groq):
    post, ri = submit
    for i, reply in enumerate(("ALLOW", "REVIEW", fake_groq.RateLimited("429"))):
        assert post(reply, str(i) * 32, comment=f"Comment number {i} about the lectures.").status_code == 200
    assert post("BLOCK", "9" * 32, comment="Some other words entirely here.").status_code == 422
    saved = rows(pg, "SELECT device_hash, status, comment_status, comment_check, comment_check_reason, "
                     "comment_check_attempts, comment_next_check_at IS NOT NULL AS due, "
                     "comment_checked_at IS NOT NULL AS checked FROM survey_ratings")
    by_device = {r["device_hash"]: r for r in saved}
    expect = {"0": ("allow", None, False, True), "1": ("review", "review", False, True),
              "2": ("unchecked", "groq_rate_limited", True, False)}
    assert len(saved) == 3
    for d, (check, reason, due, checked) in expect.items():
        row = by_device[ri.keyed_hash(SECRET, "device", d * 32)]
        assert (row["status"], row["comment_status"]) == ("accepted", "pending")
        assert (row["comment_check"], row["comment_check_reason"], row["due"], row["checked"]) == (
            check, reason, due, checked)
        assert row["comment_check_attempts"] == 1
    assert [r["outcome"] for r in rows(pg, "SELECT outcome FROM moderation_calls ORDER BY called_at")] == [
        "allow", "review", "unavailable", "block"]


def test_a_device_over_its_budget_is_saved_unchecked_without_a_call(submit, pg):
    post, ri = submit
    for i in range(ratings.DEVICE_MODERATION_BUDGET + 1):
        assert post("ALLOW", "a" * 32, comment=f"Edit {i}: the lectures were clear.").status_code == 200
    assert scalar(pg, "SELECT count(*) FROM moderation_calls") == ratings.DEVICE_MODERATION_BUDGET
    (row,) = rows(pg, "SELECT comment_check, comment_check_reason, comment_next_check_at IS NOT NULL AS due "
                      "FROM survey_ratings")
    assert row == {"comment_check": "unchecked", "comment_check_reason": "over_budget", "due": True}


# ── the queue ──

def test_the_queue_order_and_what_it_skips(pg):
    old = NOW - timedelta(hours=2)
    returning_old = insert(pg, device="d1", comment_next_check_at=old, new_device=False,
                           comment_check_reason="groq_unavailable")
    new_old = insert(pg, device="d2", comment_next_check_at=old, comment_check_reason="groq_unavailable")
    over_budget = insert(pg, device="d3", comment_next_check_at=old, new_device=False,
                         comment_check_reason="over_budget")
    insert(pg, device="d4", comment_next_check_at=NOW + timedelta(hours=1))  # not due yet
    insert(pg, device="d5", comment_next_check_at=None, comment_check_reason="duplicate")  # never queued
    insert(pg, device="d6", comment_next_check_at=old, comment_status="approved")  # a reviewer got there
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET updated_at = %s WHERE id = %s", (old - timedelta(hours=1), new_old))
    pg.commit()
    with pg.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(moderate_queue._DUE_SQL, (NOW, moderate_queue.BATCH))
        due = [r["id"] for r in cur.fetchall()]
    pg.commit()
    assert due == [returning_old, new_old, over_budget]


def test_a_queue_block_holds_the_rating_and_keeps_the_comment(pg, fake_groq):
    truncate(pg, "stats_cache")
    rating_id = insert(pg, comment_next_check_at=NOW - timedelta(minutes=1), comment_check_attempts=1,
                       hold_reasons="unverified_pair")
    summary = moderate_queue.run(pg, fake_groq("BLOCK"), now=NOW, sleep=lambda s: None)
    assert summary == "1 due: 0 clean, 0 flagged, 1 blocked, 0 failed"
    row = get(pg, rating_id)
    assert (row["status"], row["hold_reasons"]) == ("held", "unverified_pair,moderation_block")
    assert (row["comment_check"], row["comment_check_reason"], row["comment_next_check_at"]) == (
        "review", "blocked", None)
    assert row["comment"] and row["comment_status"] == "pending"
    assert scalar(pg, "SELECT value FROM stats_cache WHERE key = 'data_version'") == 1
    assert rows(pg, "SELECT source, outcome, device_hash, ip_hash FROM moderation_calls") == [
        {"source": "queue", "outcome": "block", "device_hash": None, "ip_hash": None}]


def test_an_approval_takes_the_comment_off_the_queue(pg, fake_groq):
    rating_id = insert(pg, comment_next_check_at=NOW - timedelta(minutes=1))
    with pg.cursor(cursor_factory=RealDictCursor) as cur:
        review_ratings.approve_comment(cur, rating_id[:8])
    pg.commit()
    assert get(pg, rating_id)["comment_next_check_at"] is None
    groq = fake_groq("BLOCK")
    assert moderate_queue.run(pg, groq, now=NOW, sleep=lambda s: None).startswith("0 due")
    assert groq.calls == [] and get(pg, rating_id)["status"] == "accepted"


def test_reject_comment_clears_the_check(pg):
    rating_id = insert(pg, comment_check="review", comment_check_reason="review", comment_checked_at=NOW)
    with pg.cursor(cursor_factory=RealDictCursor) as cur:
        review_ratings.reject_comment(cur, rating_id[:8])
    pg.commit()
    row = get(pg, rating_id)
    assert row["comment"] is None and all(row[c] is None for c in ratings.CHECK_COLUMNS)


# ── list and the digest ──

def test_list_and_the_digest_count_flagged_and_unchecked(pg, pg_env, capsys):
    insert(pg, device="d1", comment="Flagged words here.", comment_check="review", comment_check_reason="blocked")
    insert(pg, device="d2", comment="Clean words here.", comment_check="allow")
    insert(pg, device="d3", comment="Waiting words here.", comment_check_reason="groq_unavailable")
    insert(pg, device="d4", comment="Approved words here.", comment_check="allow", comment_status="approved")
    with pg.cursor(cursor_factory=RealDictCursor) as cur:
        review_ratings.list_pending(cur)
    pg.commit()
    out = capsys.readouterr().out
    comments = out.split("Comments to review (3):")[1].split("Pending professors")[0]
    assert comments.index("flagged: blocked") < comments.index("Clean words") < comments.index("Waiting words")
    assert "not yet checked (groq_unavailable)" in comments
    assert review_digest.main(["--dry-run"]) == 0
    assert "Comments to review: 3 (1 flagged, 1 not yet checked)" in capsys.readouterr().out
