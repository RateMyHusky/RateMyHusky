import os

import psycopg2
import psycopg2.extensions
import pytest

os.environ.setdefault("CRDB_DATABASE_URL", "postgresql://stub")
import server  # noqa: E402


def test_a_new_data_version_misses_the_old_entries(monkeypatch):
    version = {"v": 1}
    monkeypatch.setattr(server, "data_version", lambda: version["v"])
    server._cache.clear()
    server.cache_set("prof_full:x", {"a": 1})
    assert server.cache_get("prof_full:x") == {"a": 1}
    version["v"] = 2
    assert server.cache_get("prof_full:x") is None


def test_data_version_is_read_at_most_once_a_minute(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "query_one", lambda sql, params=None: calls.append(sql) or {"value": 7})
    monkeypatch.setattr(server, "_version_state", {"value": 0, "checked": 0.0})
    now = {"t": 1000.0}
    monkeypatch.setattr(server.time, "time", lambda: now["t"])
    assert server.data_version() == 7
    now["t"] += 30
    assert server.data_version() == 7 and len(calls) == 1
    now["t"] += 31
    server.data_version()
    assert len(calls) == 2


def test_a_version_change_clears_the_cache(monkeypatch):
    monkeypatch.setattr(server, "_cache", {"v1:x": {"data": 1, "ts": 0}})
    monkeypatch.setattr(server, "query_one", lambda sql, params=None: {"value": 2})
    monkeypatch.setattr(server, "_version_state", {"value": 1, "checked": 1000.0})
    now = {"t": 1061.0}
    monkeypatch.setattr(server.time, "time", lambda: now["t"])
    assert server.data_version() == 2
    assert server._cache == {}


def test_a_missing_version_row_means_version_zero(monkeypatch):
    monkeypatch.setattr(server, "query_one", lambda sql, params=None: None)
    monkeypatch.setattr(server, "_version_state", {"value": 0, "checked": 0.0})
    monkeypatch.setattr(server.time, "time", lambda: 1000.0)
    assert server.data_version() == 0


def test_ttl_is_a_day():
    assert server.CACHE_TTL == 86400


def test_cache_is_bounded_and_evicts_oldest(monkeypatch):
    monkeypatch.setattr(server, "data_version", lambda: 1)
    monkeypatch.setattr(server, "CACHE_MAX_SIZE", 2)
    server._cache.clear()
    server.cache_set("a", 1)
    server.cache_set("b", 2)
    server.cache_set("c", 3)
    assert server.cache_get("a") is None
    assert server.cache_get("b") == 2 and server.cache_get("c") == 3
    assert len(server._cache) == 2
    server.cache_set("b", 22)   # re-setting moves it to newest
    server.cache_set("d", 4)
    assert server.cache_get("c") is None
    assert server.cache_get("b") == 22 and server.cache_get("d") == 4
    server._cache.clear()


def test_a_failed_version_read_keeps_the_last_version(monkeypatch):
    def fail(sql, params=None):
        raise psycopg2.extensions.QueryCanceledError("canceling statement")

    monkeypatch.setattr(server, "query_one", fail)
    monkeypatch.setattr(server, "_version_state", {"value": 4, "checked": 1000.0})
    monkeypatch.setattr(server.time, "time", lambda: 1061.0)
    assert server.data_version() == 4


def _cancelling_conn(executed, rollback_fails=False):
    class Cur:
        def execute(self, sql, params=()):
            executed.append(sql)
            raise psycopg2.extensions.QueryCanceledError("canceling statement")

    class Conn:
        closed = 0

        def cursor(self, **kw):
            return Cur()

        def rollback(self):
            if rollback_fails:
                raise psycopg2.InterfaceError("connection already closed")
            executed.append("rollback")

    return Conn()


def test_a_cancelled_query_is_rolled_back_not_retried(monkeypatch):
    executed = []
    monkeypatch.setattr(server, "get_db", lambda: _cancelling_conn(executed))
    monkeypatch.setattr(server, "_discard_db_conn", lambda: executed.append("discard"))
    with pytest.raises(psycopg2.extensions.QueryCanceledError):
        server.query("SELECT 1")
    assert executed == ["SELECT 1", "rollback"]


def test_a_cancelled_write_is_rolled_back(monkeypatch):
    executed = []
    monkeypatch.setattr(server, "get_db", lambda: _cancelling_conn(executed))
    monkeypatch.setattr(server, "_discard_db_conn", lambda: executed.append("discard"))
    server._chat_write("INSERT 1")
    with pytest.raises(psycopg2.extensions.QueryCanceledError):
        server._write("INSERT 2")
    assert executed == ["INSERT 1", "rollback", "INSERT 2", "rollback"]


def test_a_failed_rollback_discards_the_connection(monkeypatch):
    executed = []
    monkeypatch.setattr(server, "get_db", lambda: _cancelling_conn(executed, rollback_fails=True))
    monkeypatch.setattr(server, "_discard_db_conn", lambda: executed.append("discard"))
    with pytest.raises(psycopg2.extensions.QueryCanceledError):
        server.query("SELECT 1")
    assert executed == ["SELECT 1", "discard"]
