"""db/postgres/ applies cleanly and is the schema the migration produced."""

import psycopg2.errors
import pytest

from tests.pg.pgutil import rows, scalar


def test_schema_files_apply_to_an_empty_database(pg):
    assert scalar(pg, "SELECT count(*) FROM pg_extension WHERE extname = 'vector'") == 1
    tables = {r["table_name"] for r in rows(
        pg, "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")}
    assert {"professors_catalog", "course_catalog", "source_summary", "stats_cache",
            "rmp_reviews", "evidence", "evidence_embeddings", "bookmarks",
            "usage_alerts", "rating_flags", "professor_aliases", "review_agent_runs",
            "email_sends", "rating_failures", "student_profiles", "page_views"} <= tables
    assert len(tables) == 43


def test_identity_columns_match_the_migration(pg):
    identity = {(r["table_name"], r["column_name"]) for r in rows(
        pg, "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND is_identity = 'YES'")}
    assert identity == {
        ("bookmarks", "id"), ("page_views", "id"), ("professor_photos", "id"), ("rmp_professors", "id"),
        ("rmp_reviews", "id"), ("professor_aliases", "id"),
    }


def test_test_server_speaks_ssl(pg):
    # Every connect helper hardcodes sslmode=require, so the test server must too.
    assert scalar(pg, "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()") is True


def test_profile_constraints(pg):
    cur = pg.cursor()
    cur.execute("INSERT INTO student_profiles (user_sub, grad_year, majors) VALUES ('g', NULL, '{}')")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("INSERT INTO student_profiles (user_sub, grad_year, majors) VALUES ('u', 2028, '{}')")
    pg.rollback()
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("INSERT INTO page_views (user_sub, item_type, item_key, visible_seconds, reached_section) "
                    "VALUES ('u', 'department', 'x', 5, false)")
    pg.rollback()
