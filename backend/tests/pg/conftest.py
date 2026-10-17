"""Fixtures for the PostgreSQL integration tests (backend/tests/pg/).

Skipped unless PG_TEST_URL names a local PostgreSQL 16 + pgvector server, e.g.
postgresql://postgres:test@localhost:54329/postgres?sslmode=require
(README, "PostgreSQL integration tests"). The session fixture drops and recreates
a scratch database, rmh_test, on that server and applies db/postgres/00, 02 and 03,
so every run starts from the real schema.

Refuses any host but localhost: these tests TRUNCATE tables.
"""

import os
import pathlib
from urllib.parse import urlsplit, urlunsplit

import psycopg2
import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
SCHEMA_FILES = ("00_extensions.sql", "02_tables.sql", "03_constraints.sql")
TEST_DB = "rmh_test"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _database(url, name):
    return urlunsplit(urlsplit(url)._replace(path="/" + name))


@pytest.fixture(scope="session")
def pg_url():
    base = os.getenv("PG_TEST_URL")
    if not base:
        pytest.skip("PG_TEST_URL not set; PostgreSQL integration tests skipped")
    host = urlsplit(base).hostname
    if host not in LOCAL_HOSTS:
        pytest.fail(f"PG_TEST_URL must point at a local test server, not {host!r}")
    admin = psycopg2.connect(base)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        cur.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()
    url = _database(base, TEST_DB)
    conn = psycopg2.connect(url)
    with conn.cursor() as cur:
        for name in SCHEMA_FILES:
            cur.execute((REPO / "db" / "postgres" / name).read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    return url


@pytest.fixture
def pg(pg_url):
    conn = psycopg2.connect(pg_url, options="-c timezone=UTC")
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def pg_env(pg_url, monkeypatch):
    """Point modules that read ORACLE_DATABASE_URL at call time at the test DB."""
    monkeypatch.setenv("ORACLE_DATABASE_URL", pg_url)
    return pg_url


@pytest.fixture
def live_server(pg_url, monkeypatch):
    """The server module with its pool on the test DB and the TTL cache off."""
    import server
    monkeypatch.setattr(server, "ORACLE_DATABASE_URL", pg_url)
    monkeypatch.setattr(server, "_pool", None)
    monkeypatch.setattr(server, "cache_get", lambda key: None)
    monkeypatch.setattr(server, "cache_set", lambda key, data: None)
    yield server
    if server._pool is not None:
        server._pool.closeall()
