"""moderate_queue.py with a fake connection and the FakeGroq in conftest.
Which rows come due, and in what order, is in tests/pg/test_moderate_queue_pg.py."""

from datetime import datetime, timedelta, timezone

import moderate_queue as mq

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


class FakeConn:
    def __init__(self, due, calls_today=0):
        self.due, self.calls_today = due, calls_today
        self.executed, self.commits = [], 0

    def cursor(self, cursor_factory=None):
        conn = self

        class Cur:
            rowcount = 0

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=None):
                conn.executed.append((sql, params))
                if sql.startswith("INSERT INTO moderation_calls"):
                    conn.calls_today += 1
                self.rowcount = 1
                self._rows = (conn.due if "comment_check_attempts FROM survey_ratings" in sql
                              else [{"n": conn.calls_today}] if "FROM moderation_calls" in sql else [])

            def fetchall(self):
                return list(self._rows)

            def fetchone(self):
                return self._rows[0]

        return Cur()

    def commit(self):
        self.commits += 1

    def updates(self):
        return [(s, p) for s, p in self.executed if s.startswith("UPDATE survey_ratings")]


def due(n):
    return [{"id": f"r{i}", "comment": f"comment {i}", "comment_check_attempts": 1} for i in range(n)]


def test_backoff_doubles_from_ten_minutes_up_to_six_hours():
    assert [mq.backoff(a) for a in range(7)] == [timedelta(minutes=m) for m in (10, 20, 40, 80, 160, 320, 360)]
    assert mq.backoff(30) == timedelta(hours=6)


def test_a_run_checks_up_to_fifteen_30_seconds_apart(fake_groq):
    conn, sleeps = FakeConn(due(15)), []
    summary = mq.run(conn, fake_groq("ALLOW"), now=NOW, sleep=sleeps.append)
    assert sleeps == [30] * 14
    assert summary == "15 due: 15 clean, 0 flagged, 0 blocked, 0 failed"
    select = conn.executed[0]
    assert select[1] == (NOW, 15) and "comment_status = 'pending'" in select[0]
    assert "ORDER BY COALESCE(comment_check_reason = 'over_budget', false), new_device, updated_at" in select[0]


def test_verdicts_are_recorded_only_on_the_text_checked(fake_groq):
    conn = FakeConn(due(2))
    mq.run(conn, fake_groq("REVIEW", "ALLOW"), now=NOW, sleep=lambda s: None)
    (flag_sql, flag), (clean_sql, clean) = conn.updates()
    assert flag[:4] == ("review", "review", 2, NOW) and flag[4:] == ("r0", "comment 0")
    assert clean[:2] == ("allow", None)
    assert "AND comment = %s AND comment_check = 'unchecked' AND comment_status = 'pending'" in flag_sql
    queue_calls = [p for s, p in conn.executed if s.startswith("INSERT INTO moderation_calls")]
    assert [(p[2], p[3], p[4], p[5]) for p in queue_calls] == [("queue", "review", None, None),
                                                              ("queue", "allow", None, None)]


def test_a_block_holds_the_rating_and_bumps_the_data_version(fake_groq):
    conn = FakeConn(due(1))
    assert mq.run(conn, fake_groq("BLOCK"), now=NOW, sleep=lambda s: None).endswith("1 blocked, 0 failed")
    ((sql, params),) = conn.updates()
    assert "comment_check = 'review', comment_check_reason = 'blocked'" in sql
    assert "status = 'held'" in sql and "moderation_block" in sql
    assert any(s == mq.DATA_VERSION_SQL for s, p in conn.executed)


def test_a_failure_backs_off_and_the_run_goes_on(fake_groq):
    conn = FakeConn(due(2))
    mq.run(conn, fake_groq(TimeoutError("slow"), "ALLOW"), now=NOW, sleep=lambda s: None)
    (failed_sql, failed), (_, clean) = conn.updates()
    assert failed[:3] == ("groq_unavailable", 2, NOW + timedelta(minutes=20))
    assert clean[0] == "allow"


def test_a_429_stops_the_run_and_puts_the_rest_off_to_the_next(fake_groq):
    conn = FakeConn(due(4))
    groq = fake_groq("ALLOW", fake_groq.RateLimited("429"), "ALLOW")
    summary = mq.run(conn, groq, now=NOW, sleep=lambda s: None)
    assert len(groq.calls) == 2 and summary.endswith("stopped at a 429")
    _, limited, rest = conn.updates()
    assert limited[1][:3] == ("groq_rate_limited", 2, NOW + mq.NEXT_RUN)
    assert rest[1] == (NOW + mq.NEXT_RUN, ["r2", "r3"])


def test_the_daily_cap_counts_every_call(fake_groq):
    conn = FakeConn(due(5), calls_today=mq.DAILY_CAP - 2)
    groq = fake_groq("ALLOW")
    summary = mq.run(conn, groq, now=NOW, sleep=lambda s: None)
    assert len(groq.calls) == 2 and summary.endswith(f"stopped at the daily cap of {mq.DAILY_CAP}")


def test_main_does_nothing_without_the_key(monkeypatch, capsys):
    monkeypatch.setattr(mq, "connect", lambda: (_ for _ in ()).throw(AssertionError("no DB")))
    assert mq.main() == 0
    assert "GROQ_MODERATION_KEY is not set" in capsys.readouterr().out
