"""review_agent.review_held against the real survey_ratings schema."""

import json
import uuid
from datetime import datetime, timezone

import psycopg2.extras
import pytest

import review_agent
from tests.pg.pgutil import rows, scalar, truncate


@pytest.fixture(autouse=True)
def clean(pg):
    truncate(pg, "survey_ratings", "survey_pending_courses", "professors", "banner_course_instructors", "stats_cache",
             "source_summary")


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
        counts = review_agent.review_held(cur, approve_everything)
    assert counts == {"approve": 1, "escalate": 1}

    (row,) = rows(pg, "SELECT status, agent_decision, agent_reviewed_at FROM survey_ratings WHERE id = %s", (soft,))
    assert row["status"] == "accepted" and row["agent_decision"] == "approve" and row["agent_reviewed_at"] is not None
    held = rows(pg, "SELECT status, agent_decision, agent_reviewed_at FROM survey_ratings "
                    "WHERE id::text = ANY(%s)", (group,))
    assert len(held) == 3
    assert all(r["status"] == "held" and r["agent_decision"] == "escalate" and r["agent_reviewed_at"] is not None
               for r in held)

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        assert not review_agent.review_held(cur, approve_everything)
    assert scalar(pg, "SELECT value FROM stats_cache WHERE key = 'data_version'") == 1

    # An edit bumps updated_at past the decision, so the group is sent again.
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET updated_at = %s WHERE id = %s", (datetime(2101, 1, 1, tzinfo=timezone.utc), group[0]))
    pg.commit()
    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        assert review_agent.review_held(cur, approve_everything) == {"escalate": 1}


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


def test_a_group_with_a_row_a_human_settled_mid_run_is_rolled_back_then_decided_next_run(pg, pg_url):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors (slug, name, name_key) VALUES ('sam-lee', 'Sam Lee', 'sam lee')")
    ids = [insert(pg, "sam-lee", "near_duplicate,burst_prof", f"d{i}", i) for i in (1, 2, 3)]
    pg.commit()

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_agent.review_held(cur, settle_one_while_asking(pg_url, ids[0], "escalate"))

    query = "SELECT id::text AS id, status, agent_decision, agent_reviewed_at FROM survey_ratings"
    by_id = {r["id"]: r for r in rows(pg, query)}
    assert by_id[ids[0]]["status"] == "accepted" and by_id[ids[0]]["agent_decision"] is None
    # The re-read missed the settled row, so the whole group was rolled back and recorded nothing.
    assert all(by_id[i]["status"] == "held" and by_id[i]["agent_decision"] is None
               and by_id[i]["agent_reviewed_at"] is None for i in ids[1:])

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_agent.review_held(cur, approve_everything)
    by_id = {r["id"]: r for r in rows(pg, query)}
    assert by_id[ids[0]]["agent_decision"] is None
    assert all(by_id[i]["status"] == "held" and by_id[i]["agent_decision"] == "escalate" for i in ids[1:])


def test_an_approval_rolls_the_whole_group_back_when_a_row_was_settled_mid_run(pg, pg_url):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors (slug, name, name_key) VALUES ('sam-lee', 'Sam Lee', 'sam lee')")
    ids = [insert(pg, "sam-lee", "burst_prof", f"d{i}", i, comment=VARIED[i]) for i in (0, 1)]
    pg.commit()

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_agent.review_held(cur, settle_one_while_asking(pg_url, ids[0], "approve"))

    by_id = {r["id"]: r for r in rows(pg, "SELECT id::text AS id, status, agent_decision, agent_reviewed_at "
                                           "FROM survey_ratings")}
    assert by_id[ids[0]]["status"] == "accepted" and by_id[ids[0]]["agent_decision"] is None
    assert by_id[ids[1]]["status"] == "held" and by_id[ids[1]]["agent_decision"] is None
    assert by_id[ids[1]]["agent_reviewed_at"] is None


def test_taught_counts_rmp_and_reviewer_vouched_pairs_like_the_rate_route(pg):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO source_summary (professor_slug, course_code, source, num_ratings) "
                    "VALUES ('sam-lee', 'CS2500', 'rmp', 4)")
    insert(pg, "sam-lee", "burst_prof", "d1", 0)
    other = insert(pg, "sam-lee", "burst_prof", "d2", 1)
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET course_code = 'CS3500' WHERE id = %s", (other,))
    pg.commit()
    seen = []
    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_agent.review_held(cur, lambda m: seen.append(json.loads(m[1]["content"])["taught"]) or "{}",
                                 dry_run=True)
    assert seen == [{"CS2500": True, "CS3500": False}]


def test_an_escalate_from_before_skew_week_is_reviewed_again_with_it(pg):
    import ratings

    # Escalated alone as too_fast. A skew trigger days later, past GROUP_GAP, is in a group of its own,
    # so without the escalate cleared this row would never be sent with skew_week.
    row = insert(pg, "sam-lee", "too_fast", "d1", 0)
    with pg.cursor() as cur:
        # After the row's updated_at, so the escalate isn't stale on its own.
        cur.execute("UPDATE survey_ratings SET agent_decision = 'escalate', agent_reason = 'fast', "
                    "agent_reviewed_at = %s WHERE id = %s", (datetime(2100, 1, 1, tzinfo=timezone.utc), row))
    pg.commit()

    def write(sql, params):
        with pg.cursor() as cur:
            cur.execute(sql, params)
        pg.commit()

    key = {"professor_slug": "sam-lee", "pending_professor_id": None, "course_code": "CS2500",
           "pending_course_id": None}
    ratings.hold_skew_week(key, write, datetime(2026, 10, 31, tzinfo=timezone.utc))
    seen = []
    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_agent.review_held(cur, lambda m: seen.append(json.loads(m[1]["content"])["hold_reasons"]) or "{}",
                                 dry_run=True)
    assert seen == [["skew_week", "too_fast"]]


def test_no_transaction_is_open_while_the_model_answers(pg, pg_url):
    insert(pg, "sam-lee", "no_timer", "d1", 0)
    pg.commit()
    agent = psycopg2.connect(pg_url, options="-c timezone=UTC")
    states = []

    def ask(messages):
        states.append(rows(pg, "SELECT state FROM pg_stat_activity WHERE pid = %s",
                           (agent.get_backend_pid(),))[0]["state"])
        return json.dumps({"decision": "escalate", "recommend_reject": False, "reason": "x"})

    with agent.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_agent.review_held(cur, ask)
    agent.close()
    assert states == ["idle"]


def test_a_resubmit_during_the_run_does_not_make_the_new_decision_stale(pg, pg_url):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors (slug, name, name_key) VALUES ('jane-doe', 'Jane Doe', 'jane doe')")
    first = insert(pg, "jane-doe", "unverified_pair", "d0", 0)
    pg.commit()
    other = psycopg2.connect(pg_url)

    def ask(messages):
        # A no-op resubmit of the first rating while the model answers bumps only updated_at.
        with other.cursor() as cur:
            cur.execute("UPDATE survey_ratings SET updated_at = now() WHERE id = %s", (first,))
        other.commit()
        return approve_everything(messages)

    try:
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            review_agent.review_held(cur, ask)
    finally:
        other.close()
    held = rows(pg, "SELECT agent_decision, agent_reviewed_at, updated_at FROM survey_ratings")
    assert [review_agent.decision_of(r) for r in held] == ["escalate"]


def seed_banner(pg, slug, codes):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors (slug, name, name_key) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (slug, slug, slug))
        for code in codes:
            cur.execute(
                "INSERT INTO banner_course_offerings (subject_course, subject, course_title, first_term_code, "
                "last_term_code, last_term_label, terms_offered, pattern, fall_years, spring_years, summer_years, "
                "pattern_window_years, instructor_count) VALUES (%s, %s, 'Course', '202210', '202710', "
                "'Fall 2026', 1, 'Fall', 1, 0, 0, 5, 1) ON CONFLICT DO NOTHING", (code, code[:4]))
            cur.execute(
                "INSERT INTO banner_course_instructors (subject_course, instructor_key, professor_slug, "
                "match_method, terms_taught, sections, first_term_code, last_term_code, last_term_label) "
                "VALUES (%s, %s, %s, 'exact', 1, 1, '202210', '202710', 'Fall 2026')", (code, slug, slug))
    pg.commit()


def pending_course(pg, code, *slugs_and_devices):
    """A pending course with an accepted rating per (professor slug, device)."""
    course_id = str(uuid.uuid4())
    with pg.cursor() as cur:
        cur.execute("INSERT INTO survey_pending_courses (id, code, name) VALUES (%s, %s, 'Typo')", (course_id, code))
        for slug, device in slugs_and_devices:
            cur.execute(
                "INSERT INTO survey_ratings (id, professor_slug, pending_course_id, term_label, rating, hours, "
                "status, device_hash, new_device, network_type) "
                "VALUES (%s, %s, %s, 'Fall 2025', 4, '3-4', 'accepted', %s, false, 'unknown')",
                (str(uuid.uuid4()), slug, course_id, device))
    pg.commit()
    return course_id


def run_courses(pg):
    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        return review_agent.review_pending_courses(cur, datetime.now(timezone.utc))


def test_bio2299_merges_and_envr1110_escalates(pg):
    seed_banner(pg, "jane-doe", ["BIOL2299", "ENVR1101", "ENVR1120"])
    bio = pending_course(pg, "BIO2299", ("jane-doe", "d1"))
    envr = pending_course(pg, "ENVR1110", ("jane-doe", "d2"))

    assert run_courses(pg) == {"merge": 1, "escalate": 1}

    got = {r["id"]: r for r in rows(pg, "SELECT id::text AS id, status, resolved_code, agent_decision, "
                                        "agent_reason FROM survey_pending_courses")}
    assert (got[bio]["status"], got[bio]["resolved_code"], got[bio]["agent_decision"]) == ("merged", "BIOL2299", "merge")
    assert got[bio]["agent_reason"] == "one edit from BIOL2299; 1 rating(s)"
    assert (got[envr]["status"], got[envr]["agent_decision"]) == ("pending", "escalate")
    assert got[envr]["agent_reason"] == "jane-doe: 2 candidates (ENVR1101, ENVR1120)"
    assert rows(pg, "SELECT course_code FROM survey_ratings WHERE device_hash = 'd1'") == [{"course_code": "BIOL2299"}]

    # Every pending course is checked on every run, so the escalated one escalates again.
    assert run_courses(pg) == {"escalate": 1}
    assert scalar(pg, "SELECT agent_reason FROM survey_pending_courses WHERE id = %s", (envr,)) == \
        "jane-doe: 2 candidates (ENVR1101, ENVR1120)"


def test_a_merge_across_two_professors_keeps_the_newer_rating_per_device(pg):
    seed_banner(pg, "jane-doe", ["ACCT1201"])
    seed_banner(pg, "bob-lee", ["ACCT1201"])
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO survey_ratings (id, professor_slug, course_code, term_label, rating, hours, status, "
            "device_hash, new_device, network_type, created_at, updated_at) VALUES (%s, 'jane-doe', 'ACCT1201', "
            "'Fall 2025', 1, '3-4', 'accepted', 'd1', false, 'unknown', '2026-01-01', '2026-01-01')",
            (str(uuid.uuid4()),))
    pg.commit()
    pending_course(pg, "ACC1201", ("jane-doe", "d1"), ("bob-lee", "d2"))

    assert run_courses(pg) == {"merge": 1}

    assert rows(pg, "SELECT professor_slug, course_code, rating FROM survey_ratings WHERE device_hash = 'd1'") == [
        {"professor_slug": "jane-doe", "course_code": "ACCT1201", "rating": 4}]
    assert scalar(pg, "SELECT count(*) FROM survey_ratings") == 2


def test_a_course_escalated_for_a_held_rating_is_merged_once_that_rating_is_approved(pg):
    seed_banner(pg, "jane-doe", ["BIOL2299"])
    course = pending_course(pg, "BIO2299", ("jane-doe", "d1"))
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET status = 'held', hold_reasons = 'no_timer' WHERE pending_course_id = %s",
                    (course,))
    pg.commit()

    assert run_courses(pg) == {"escalate": 1}
    assert scalar(pg, "SELECT agent_reason FROM survey_pending_courses WHERE id = %s", (course,)) == "a rating on it is held"
    assert run_courses(pg) == {"escalate": 1}

    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET status = 'accepted' WHERE pending_course_id = %s", (course,))
    pg.commit()

    assert run_courses(pg) == {"merge": 1}
    assert rows(pg, "SELECT status, resolved_code FROM survey_pending_courses") == [
        {"status": "merged", "resolved_code": "BIOL2299"}]
