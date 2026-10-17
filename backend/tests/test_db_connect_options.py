"""Every connect helper must open a UTC session over SSL.

The previous database's sessions were UTC by default; PostgreSQL uses the
server/role TimeZone. The Groq budget, throttle and usage-alert queries compute "today" in
SQL while the Python side computes it in UTC, so every session pins UTC.
"""

import importlib
import os
import pathlib
import sys

import psycopg2
import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scraper"))

CONNECTORS = [
    ("pipeline.db", lambda m: m.connect()),
    ("load_rmp", lambda m: m.get_connection()),
    ("moderate_backfill", lambda m: m.connect()),
    ("rag.clear_ask_strikes", lambda m: m.connect()),
    ("rag.eval.eval_common", lambda m: m.connect()),
    ("load_evidence", lambda m: m.connect()),
    ("load_reddit", lambda m: m.connect()),
    ("load_catalog", lambda m: m.connect(os.environ["ORACLE_DATABASE_URL"])),
    ("load_banner", lambda m: m.connect(os.environ["ORACLE_DATABASE_URL"])),
]


@pytest.mark.parametrize("module_name,call", CONNECTORS, ids=[c[0] for c in CONNECTORS])
def test_every_connect_helper_pins_utc_over_ssl(monkeypatch, module_name, call):
    calls = []
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: calls.append(k) or object())
    call(importlib.import_module(module_name))
    assert len(calls) == 1
    assert calls[0].get("sslmode") == "require"
    assert "-c timezone=UTC" in calls[0].get("options", "")


def test_database_url_reads_only_oracle_database_url(monkeypatch):
    from pipeline import db
    monkeypatch.setenv("ORACLE_DATABASE_URL", "postgresql://only-this")
    monkeypatch.setenv("CRDB_" + "DATABASE_URL", "postgresql://not-this")
    assert db.database_url() == "postgresql://only-this"


def test_server_pool_pins_utc_and_the_statement_timeout(monkeypatch):
    import server
    captured = {}

    class FakePool:
        def __init__(self, minconn, maxconn, dsn, **kwargs):
            captured.update(kwargs, minconn=minconn, maxconn=maxconn)

    monkeypatch.setattr(server, "ThreadedConnectionPool", FakePool)
    monkeypatch.setattr(server, "_pool", None)
    server._get_pool()
    assert captured["options"] == "-c statement_timeout=5000 -c timezone=UTC"
    assert (captured["minconn"], captured["maxconn"]) == (5, 10)
    assert captured["sslmode"] == "require"
