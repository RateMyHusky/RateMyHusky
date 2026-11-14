"""Unit tests for key_pool.py — round-robin API-key selection with RPD/TPD
limits and cooldown-based retirement.

No network/secrets: KeyPool takes injected entries and a usage_fn, and
load_entries is driven entirely by env vars / a temp file via monkeypatch.
"""
import json
import pytest
from rag import key_pool
from rag.key_pool import KeyPool, load_entries, _entry, DEFAULT_RPD, DEFAULT_TPD


ENTRIES = [
    {"key": "k1", "rpd_limit": 1000, "tpd_limit": 500000},
    {"key": "k2", "rpd_limit": 1000, "tpd_limit": 500000},
]


def pool(usage, entries=ENTRIES):
    return KeyPool(entries, usage_fn=lambda k: usage[k])


class TestAcquire:
    def test_returns_first_when_all_clear(self):
        p = pool({"k1": {"rpd": 0, "tpd": 0}, "k2": {"rpd": 0, "tpd": 0}})
        assert p.acquire(est_tokens=10)["key"] == "k1"

    def test_advances_past_rpd_exhausted_entry(self):
        p = pool({"k1": {"rpd": 1000, "tpd": 0}, "k2": {"rpd": 0, "tpd": 0}})
        assert p.acquire(est_tokens=10)["key"] == "k2"

    def test_tpd_overflow_blocks_entry(self):
        # est_tokens pushes tpd over the limit on both keys -> nothing usable
        p = pool({"k1": {"rpd": 0, "tpd": 499999}, "k2": {"rpd": 0, "tpd": 499999}})
        assert p.acquire(est_tokens=1800) is None

    def test_tpd_exactly_at_limit_is_allowed(self):
        # boundary: u["tpd"] + est == limit is allowed (only strictly-over fails)
        p = pool({"k1": {"rpd": 0, "tpd": 499000}, "k2": {"rpd": 0, "tpd": 0}})
        assert p.acquire(est_tokens=1000)["key"] == "k1"

    def test_rpd_at_limit_blocks(self):
        # boundary: rpd >= limit fails (equal counts as exhausted)
        p = pool({"k1": {"rpd": 1000, "tpd": 0}, "k2": {"rpd": 1000, "tpd": 0}})
        assert p.acquire(est_tokens=10) is None

    def test_empty_pool_returns_none(self):
        assert KeyPool([]).acquire(10) is None

    def test_acquire_updates_current_index(self):
        p = pool({"k1": {"rpd": 1000, "tpd": 0}, "k2": {"rpd": 0, "tpd": 0}})
        p.acquire(est_tokens=10)
        assert p.current()["key"] == "k2"


class TestRetire:
    def test_retired_key_is_skipped(self, monkeypatch):
        monkeypatch.setattr(key_pool.time, "time", lambda: 1000.0)
        p = pool({"k1": {"rpd": 0, "tpd": 0}, "k2": {"rpd": 0, "tpd": 0}})
        p.acquire(est_tokens=10)          # lands on k1
        p.retire("k1", cooldown_seconds=60)
        assert p.acquire(est_tokens=10)["key"] == "k2"

    def test_retire_advances_index_off_current(self, monkeypatch):
        monkeypatch.setattr(key_pool.time, "time", lambda: 1000.0)
        p = pool({"k1": {"rpd": 0, "tpd": 0}, "k2": {"rpd": 0, "tpd": 0}})
        p.acquire(est_tokens=10)          # current == k1
        p.retire("k1")
        assert p.current()["key"] == "k2"

    def test_cooldown_expires_and_key_recovers(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(key_pool.time, "time", lambda: now[0])
        p = pool({"k1": {"rpd": 0, "tpd": 0}, "k2": {"rpd": 0, "tpd": 0}})
        p.acquire(est_tokens=10)
        p.retire("k1", cooldown_seconds=60)
        assert p.acquire(est_tokens=10)["key"] == "k2"   # still cooling
        now[0] += 61
        # k1 is acquirable again, and the expired cooldown entry is purged
        assert p._covers(ENTRIES[0], 10) is True
        assert "k1" not in p.exhausted


class TestLoadEntries:
    def test_env_groq_keys_contiguous(self, monkeypatch):
        monkeypatch.setenv("groq1", "aaa")
        monkeypatch.setenv("groq2", "bbb")
        monkeypatch.delenv("groq3", raising=False)
        entries = load_entries()
        assert [e["key"] for e in entries] == ["aaa", "bbb"]
        assert entries[0]["rpd_limit"] == DEFAULT_RPD
        assert entries[0]["tpd_limit"] == DEFAULT_TPD

    def test_env_keys_stop_at_first_gap(self, monkeypatch):
        monkeypatch.setenv("groq1", "aaa")
        monkeypatch.delenv("groq2", raising=False)  # gap -> groq3 never read
        monkeypatch.setenv("groq3", "ccc")
        assert [e["key"] for e in load_entries()] == ["aaa"]

    def test_comma_separated_groq_api_keys(self, monkeypatch, tmp_path):
        for n in range(1, 5):
            monkeypatch.delenv("groq%d" % n, raising=False)
        monkeypatch.setattr(key_pool, "KEY_STORE", str(tmp_path / "missing.json"))
        monkeypatch.setenv("GROQ_API_KEYS", " aaa, bbb ,,")
        monkeypatch.setenv("GROQ_API_KEY", "solo")
        entries = load_entries()
        assert [e["key"] for e in entries] == ["aaa", "bbb"]
        assert entries[0]["tpd_limit"] == DEFAULT_TPD

    def test_numbered_keys_win_over_groq_api_keys(self, monkeypatch):
        monkeypatch.setenv("groq1", "aaa")
        monkeypatch.delenv("groq2", raising=False)
        monkeypatch.setenv("GROQ_API_KEYS", "zzz")
        assert [e["key"] for e in load_entries()] == ["aaa"]

    def test_json_store_fallback(self, monkeypatch, tmp_path):
        for n in range(1, 5):
            monkeypatch.delenv("groq%d" % n, raising=False)
        monkeypatch.delenv("GROQ_API_KEYS", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        store = tmp_path / "keys.json"
        store.write_text(json.dumps({"keys": [_entry("fromfile")]}))
        monkeypatch.setattr(key_pool, "KEY_STORE", str(store))
        assert [e["key"] for e in load_entries()] == ["fromfile"]

    def test_single_env_key_last_resort(self, monkeypatch, tmp_path):
        for n in range(1, 5):
            monkeypatch.delenv("groq%d" % n, raising=False)
        monkeypatch.delenv("GROQ_API_KEYS", raising=False)
        monkeypatch.setattr(key_pool, "KEY_STORE", str(tmp_path / "missing.json"))
        monkeypatch.setenv("GROQ_API_KEY", "solo")
        assert [e["key"] for e in load_entries()] == ["solo"]

    def test_no_keys_anywhere_returns_empty(self, monkeypatch, tmp_path):
        for n in range(1, 5):
            monkeypatch.delenv("groq%d" % n, raising=False)
        monkeypatch.delenv("GROQ_API_KEYS", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setattr(key_pool, "KEY_STORE", str(tmp_path / "missing.json"))
        assert load_entries() == []
