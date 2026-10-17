"""Sessions really are UTC with the 5s statement timeout, end to end."""

from tests.pg.pgutil import scalar


def test_pipeline_connect_opens_a_utc_session(pg_env):
    from pipeline import db
    conn = db.connect()
    try:
        assert scalar(conn, "SHOW timezone") == "UTC"
    finally:
        conn.close()


def test_server_pool_sessions_are_utc_with_a_statement_timeout(live_server):
    with live_server.app.app_context():
        row = live_server.query_one(
            "SELECT current_setting('TimeZone') AS tz, "
            "current_setting('statement_timeout') AS st")
    assert row == {"tz": "UTC", "st": "5s"}
