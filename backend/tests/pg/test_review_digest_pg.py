"""The digest's queries against real PostgreSQL: rating counts, the 14-day chart, usage meters, names."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

import review_digest
from tests.pg.pgutil import truncate

NOW = datetime.now(timezone.utc)
TABLES = ("survey_ratings", "professors", "moderation_calls", "review_agent_runs", "ask_log", "email_sends",
          "rating_failures")


@pytest.fixture(autouse=True)
def clean(pg):
    truncate(pg, *TABLES)
    yield
    truncate(pg, *TABLES)


def rating(cur, days_ago, status, comment_status=None, hours_ago=None):
    created = NOW - (timedelta(hours=hours_ago) if hours_ago is not None else timedelta(days=days_ago))
    cur.execute("INSERT INTO survey_ratings (id, professor_slug, course_code, rating, hours, status, device_hash, "
                "new_device, network_type, comment, comment_status, created_at) VALUES "
                "(%s, 'jane-doe', 'CS2500', 4, '3-4', %s, %s, true, 'other', %s, %s, %s)",
                (str(uuid.uuid4()), status, str(uuid.uuid4()), "Fine." if comment_status else None, comment_status, created))


def seed(pg):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors (slug, name, name_key) VALUES ('jane-doe', 'Jane Doe', 'jane doe')")
        # At most half the time since UTC midnight ago (up to 1 hour), so they stay on today's UTC date.
        today = min(1, (NOW - NOW.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 7200)
        rating(cur, 0, "accepted", "approved", hours_ago=today)
        rating(cur, 0, "held", hours_ago=today)
        rating(cur, 13, "accepted")
        rating(cur, 15, "accepted")
        cur.execute("INSERT INTO moderation_calls (id, source, outcome, tokens) VALUES "
                    "(%s, 'submit', 'block', 500), (%s, 'queue', 'allow', NULL)", (str(uuid.uuid4()), str(uuid.uuid4())))
        cur.execute("INSERT INTO review_agent_runs (requests, tokens, keys) VALUES (10, 4000, 6)")
        cur.execute("INSERT INTO ask_log (query, mode, result_status, tokens_used) VALUES "
                    "('q', 'm', 'ok', 1000), ('q', 'm', 'ok', NULL)")
        cur.execute("INSERT INTO email_sends (sent_at) VALUES (now()), (date_trunc('month', now(), 'UTC')), "
                    "(now() - interval '40 days')")
    pg.commit()


def test_rating_stats_counts_the_last_day_and_fourteen_utc_days(pg):
    seed(pg)
    stats = review_digest.rating_stats(pg, NOW)
    assert stats["new"] == 2 and stats["live"] == 1 and stats["held"] == 1 and stats["rejected"] == 1
    assert stats["live_all"] == 3 and stats["comments_all"] == 1
    assert len(stats["days"]) == 14
    assert stats["days"][0] == (1, 0)
    assert stats["days"][13] == (1, 1)
    assert sum(a + b for a, b in stats["days"]) == 3


def test_rating_stats_counts_devices_and_the_most_rated(pg):
    with pg.cursor() as cur:
        for slug, code, device, new, hours in (("jane-doe", "CS2500", "d1", True, 1), ("jane-doe", "CS3500", "d1", True, 2),
                                               ("jane-doe", "CS2500", "d2", False, 3), ("zed", "CS2500", "d3", True, 4),
                                               (None, "CS2500", "d4", True, 5), ("old", "OLD1000", "d5", True, 48)):
            cur.execute("INSERT INTO survey_ratings (id, professor_slug, pending_professor_id, course_code, rating, hours, "
                        "status, device_hash, new_device, network_type, created_at) VALUES "
                        "(%s, %s, %s, %s, 4, '3-4', 'accepted', %s, %s, 'other', now() - %s * interval '1 hour')",
                        (str(uuid.uuid4()), slug, None if slug else str(uuid.uuid4()), code, device, new, hours))
    pg.commit()
    stats = review_digest.rating_stats(pg, NOW)
    assert stats["devices"] == 4 and stats["new_devices"] == 3
    assert stats["top_professors"] == [("jane-doe", 3), ("zed", 1)]
    assert stats["top_courses"] == [("CS2500", 4), ("CS3500", 1)]


def test_failure_counts_sum_the_24_whole_hours_before_this_one(pg):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO rating_failures (hour, reason, n) VALUES "
                    "(date_trunc('hour', now()), 'invalid', 50), "  # this hour: tomorrow's digest
                    "(date_trunc('hour', now()) - interval '1 hour', 'invalid', 2), "
                    "(date_trunc('hour', now()) - interval '1 day', 'invalid', 1), "
                    "(date_trunc('hour', now()) - interval '1 day 1 hour', 'invalid', 70), "  # yesterday's
                    "(date_trunc('hour', now()) - interval '3 hours', 'captcha_failed', 9)")
    pg.commit()
    assert review_digest.failure_counts(pg) == [("captcha_failed", 9), ("invalid", 3)]


def test_server_failure_insert_counts_up_within_the_hour(pg):
    import os
    os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")
    os.environ.setdefault("JWT_SECRET", "test-secret")
    import server
    with pg.cursor() as cur:
        for reason in ("invalid", "invalid", "rule_block"):
            cur.execute(server.RATING_FAILURE_SQL, (reason,))
    pg.commit()
    with pg.cursor() as cur:
        cur.execute("UPDATE rating_failures SET hour = hour - interval '1 hour'")
    pg.commit()
    assert review_digest.failure_counts(pg) == [("invalid", 2), ("rule_block", 1)]


def test_checker_stats_count_outcomes_and_comments_still_unchecked(pg):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO moderation_calls (id, source, outcome, called_at) VALUES "
                    "(gen_random_uuid(), 'submit', 'allow', now()), (gen_random_uuid(), 'queue', 'allow', now()), "
                    "(gen_random_uuid(), 'queue', 'unavailable', now()), (gen_random_uuid(), 'submit', 'block', now()), "
                    "(gen_random_uuid(), 'queue', 'review', now() - interval '2 days')")
        for check, attempts, status in (("unchecked", 0, "pending"), ("unchecked", 3, "pending"),
                                        ("unchecked", 5, "approved"), ("review", 1, "pending")):
            cur.execute("INSERT INTO survey_ratings (id, professor_slug, course_code, rating, hours, status, device_hash, "
                        "new_device, network_type, comment, comment_status, comment_check, comment_check_attempts) "
                        "VALUES (%s, 'jane-doe', 'CS2500', 4, '3-4', 'accepted', %s, true, 'other', 'Fine.', %s, %s, %s)",
                        (str(uuid.uuid4()), str(uuid.uuid4()), status, check, attempts))
    pg.commit()
    assert review_digest.checker_stats(pg) == {"allow": 2, "review": 0, "block": 1, "unavailable": 1,
                                               "waiting": 2, "stuck": 1}


def test_usage_meters_count_sends_by_utc_day_and_month_and_sum_groq(pg):
    seed(pg)
    meters = review_digest.usage_meters(pg)
    # The month-start send is also today's on the 1st.
    today = 2 if datetime.now(timezone.utc).day == 1 else 1
    assert meters[0] == {"label": "Resend today", "used": today, "limit": 100, "unit": ""}
    assert meters[1] == {"label": "Resend month", "used": 2, "limit": 3000, "unit": ""}
    assert meters[2] == {"label": "Groq chat + agent", "used": 5000, "limit": 1_200_000, "unit": "tokens"}
    assert meters[3] == {"label": "Groq checker", "used": 500, "limit": 200_000, "unit": "tokens"}


def test_groq_agent_meter_counts_todays_run_and_a_rolling_day_of_chat(pg):
    # One second before UTC midnight is always inside a rolling 24 hours: yesterday's run is left out,
    # but chat from then still counts, since the digest at 13:00 UTC would otherwise miss Boston's daytime.
    with pg.cursor() as cur:
        cur.execute("INSERT INTO review_agent_runs (ran_at, requests, tokens, keys) VALUES "
                    "(date_trunc('day', now(), 'UTC') - interval '1 second', 900, 150000, 1), (now(), 10, 4000, 1)")
        cur.execute("INSERT INTO ask_log (query, mode, result_status, tokens_used, created_at) VALUES "
                    "('q', 'm', 'ok', 2000, date_trunc('day', now(), 'UTC') - interval '1 second'), "
                    "('q', 'm', 'ok', 7000, now() - interval '25 hours')")
    pg.commit()
    assert review_digest.usage_meters(pg)[2] == {"label": "Groq chat + agent", "used": 6000, "limit": 200_000, "unit": "tokens"}


def test_groq_checker_meter_counts_only_calls_that_reached_groq(pg):
    # OpenAI-fallback calls and failed Groq attempts are recorded with no tokens.
    with pg.cursor() as cur:
        cur.execute("INSERT INTO moderation_calls (id, source, outcome, tokens) VALUES "
                    "(%s, 'submit', 'allow', NULL), (%s, 'submit', 'unavailable', NULL), (%s, 'submit', 'allow', 100)",
                    (str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())))
    pg.commit()
    assert review_digest.usage_meters(pg)[3] == {"label": "Groq checker", "used": 1, "limit": 1000, "unit": "requests"}


def test_groq_agent_limit_uses_the_last_run_that_had_keys(pg):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO review_agent_runs (ran_at, requests, tokens, keys) VALUES "
                    "(now() - interval '2 days', 0, 0, 6), (now(), 0, 0, 0)")
    pg.commit()
    assert review_digest.usage_meters(pg)[2]["limit"] == 6000


def test_usage_meters_on_an_empty_database_assume_one_key(pg):
    meters = review_digest.usage_meters(pg)
    assert [m["label"] for m in meters] == ["Resend today", "Resend month", "Groq chat + agent", "Groq checker"]
    assert meters[0]["used"] == 0 and meters[1]["used"] == 0
    assert meters[2]["used"] == 0 and meters[2]["limit"] == 1000


def test_main_dry_run_shows_professor_names(pg, pg_env, capsys):
    seed(pg)
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'no_timer', "
                    "agent_decision = 'approve', agent_reviewed_at = now() WHERE comment_status = 'approved'")
    pg.commit()
    assert review_digest.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Jane Doe" in out and "HTML preview:" in out
    assert "Most rated professors\nJane Doe: 2" in out and "Comment checker\nPassed: 1" in out
