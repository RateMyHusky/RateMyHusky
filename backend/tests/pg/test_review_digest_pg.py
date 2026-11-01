"""The digest's queries against real PostgreSQL: rating counts, the 14-day chart, usage meters, names."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

import review_digest
from tests.pg.pgutil import truncate

NOW = datetime.now(timezone.utc)
TABLES = ("survey_ratings", "professors", "moderation_calls", "review_agent_runs", "ask_log", "email_sends")


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


def test_usage_meters_count_sends_by_utc_day_and_month_and_sum_groq(pg):
    seed(pg)
    meters = review_digest.usage_meters(pg)
    # The month-start send is also today's on the 1st.
    today = 2 if datetime.now(timezone.utc).day == 1 else 1
    assert meters[0] == {"label": "Resend today", "used": today, "limit": 100, "unit": ""}
    assert meters[1] == {"label": "Resend month", "used": 2, "limit": 3000, "unit": ""}
    assert meters[2] == {"label": "Groq agent", "used": 5000, "limit": 1_200_000, "unit": "tokens"}
    assert meters[3] == {"label": "Groq checker", "used": 500, "limit": 200_000, "unit": "tokens"}


def test_usage_meters_on_an_empty_database_fall_back_to_the_configured_keys(pg):
    meters = review_digest.usage_meters(pg)
    assert [m["label"] for m in meters] == ["Resend today", "Resend month", "Groq agent", "Groq checker"]
    assert meters[0]["used"] == 0 and meters[1]["used"] == 0
    assert meters[2]["used"] == 0 and meters[2]["limit"] >= 1000


def test_main_dry_run_shows_professor_names(pg, pg_env, capsys):
    seed(pg)
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'no_timer', "
                    "agent_decision = 'approve', agent_reviewed_at = now() WHERE comment_status = 'approved'")
    pg.commit()
    assert review_digest.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Jane Doe" in out and "HTML preview:" in out
