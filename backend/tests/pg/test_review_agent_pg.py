"""review_agent.review_held against the real survey_ratings schema."""

import json
import uuid
from datetime import datetime, timezone

import psycopg2.extras
import pytest

import review_agent
from tests.pg.pgutil import rows, truncate

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean(pg):
    truncate(pg, "survey_ratings", "survey_pending_courses", "professors", "banner_course_instructors")


def insert(pg, slug, reasons, device, minute, comment=None):
    new_id = str(uuid.uuid4())
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO survey_ratings (id, professor_slug, course_code, term_label, rating, hours, comment, "
            "status, hold_reasons, device_hash, new_device, network_type, created_at) "
            "VALUES (%s, %s, 'CS2500', 'Fall 2025', 4, '3-4', %s, 'held', %s, %s, true, 'unknown', %s)",
            (new_id, slug, comment or f"Lecture {device} covered topic {device} in depth.", reasons, device,
             f"2026-10-27T10:{minute:02d}:00Z"))
    return new_id


def approve_everything(messages):
    return json.dumps({"decision": "approve", "recommend_reject": False, "reason": "looks fine"})


def test_soft_flag_is_approved_and_a_near_duplicate_group_stays_held(pg):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors (slug, name, name_key) VALUES ('jane-doe', 'Jane Doe', 'jane doe')")
        cur.execute("INSERT INTO professors (slug, name, name_key) VALUES ('sam-lee', 'Sam Lee', 'sam lee')")
    soft = insert(pg, "jane-doe", "no_timer", "d0", 0)
    group = [insert(pg, "sam-lee", "near_duplicate,burst_prof", f"d{i}", i) for i in (1, 2, 3)]
    pg.commit()

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        counts = review_agent.review_held(cur, approve_everything, NOW)
    assert counts == {"approve": 1, "escalate": 1}

    (row,) = rows(pg, "SELECT status, agent_decision, agent_reviewed_at FROM survey_ratings WHERE id = %s", (soft,))
    assert row["status"] == "accepted" and row["agent_decision"] == "approve" and row["agent_reviewed_at"] == NOW
    held = rows(pg, "SELECT status, agent_decision, agent_reviewed_at FROM survey_ratings "
                    "WHERE id::text = ANY(%s)", (group,))
    assert len(held) == 3
    assert all(r["status"] == "held" and r["agent_decision"] == "escalate" and r["agent_reviewed_at"] == NOW
               for r in held)

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        assert not review_agent.review_held(cur, approve_everything, NOW)


VARIED = ["The recursion unit was taught with live coding and weekly quizzes that matched the exams closely.",
          "Graded the labs slowly, but office hours on sorting and hashing were genuinely useful every week."]


def settle_one_while_asking(pg_url, victim, reply):
    """An `ask` that, mid-run, accepts one rating on another connection, as a human would."""
    def ask(messages):
        other = psycopg2.connect(pg_url)
        with other.cursor() as cur:
            cur.execute("UPDATE survey_ratings SET status = 'accepted' WHERE id = %s", (victim,))
        other.commit()
        other.close()
        return json.dumps({"decision": reply, "recommend_reject": False, "reason": "x"})
    return ask


def test_an_escalate_does_not_stamp_a_row_a_human_settled_mid_run(pg, pg_url):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors (slug, name, name_key) VALUES ('sam-lee', 'Sam Lee', 'sam lee')")
    ids = [insert(pg, "sam-lee", "near_duplicate,burst_prof", f"d{i}", i) for i in (1, 2, 3)]
    pg.commit()

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_agent.review_held(cur, settle_one_while_asking(pg_url, ids[0], "escalate"), NOW)

    by_id = {r["id"]: r for r in rows(pg, "SELECT id::text AS id, status, agent_decision FROM survey_ratings")}
    assert by_id[ids[0]]["status"] == "accepted" and by_id[ids[0]]["agent_decision"] is None
    assert all(by_id[i]["status"] == "held" and by_id[i]["agent_decision"] == "escalate" for i in ids[1:])


def test_an_approval_rolls_the_whole_group_back_when_a_row_was_settled_mid_run(pg, pg_url):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors (slug, name, name_key) VALUES ('sam-lee', 'Sam Lee', 'sam lee')")
    ids = [insert(pg, "sam-lee", "burst_prof", f"d{i}", i, comment=VARIED[i]) for i in (0, 1)]
    pg.commit()

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_agent.review_held(cur, settle_one_while_asking(pg_url, ids[0], "approve"), NOW)

    by_id = {r["id"]: r for r in rows(pg, "SELECT id::text AS id, status, agent_decision, agent_reviewed_at "
                                           "FROM survey_ratings")}
    assert by_id[ids[0]]["status"] == "accepted" and by_id[ids[0]]["agent_decision"] is None
    assert by_id[ids[1]]["status"] == "held" and by_id[ids[1]]["agent_decision"] is None
    assert by_id[ids[1]]["agent_reviewed_at"] is None
