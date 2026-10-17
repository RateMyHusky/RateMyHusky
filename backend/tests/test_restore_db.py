"""restore_db: section filtering, DELETE injection, and never a partial commit."""

import gzip
import os
import time

import pytest

import restore_db

LINES = restore_db._FIXTURE_SQL.splitlines(keepends=True)


def test_selftest_passes():
    assert restore_db.selftest() == 0


def test_dump_tables_lists_data_sections_in_order():
    assert restore_db.dump_tables(LINES) == ["rmp_reviews", "stats_cache"]


def test_sequence_sections_belong_to_their_table():
    assert restore_db.section_table("SEQUENCE SET", "rmp_reviews_id_seq") == "rmp_reviews"
    assert restore_db.section_table("SEQUENCE SET", "prof_rmp_link_rowid_seq") == "prof_rmp_link"
    assert restore_db.section_table("TABLE DATA", "stats_cache") == "stats_cache"


def test_filter_keeps_selected_sections_and_injects_one_delete():
    out = "".join(restore_db.filter_dump(LINES, {"rmp_reviews"}))
    assert out.count('DELETE FROM public."rmp_reviews";') == 1
    assert out.count("DELETE FROM") == 1
    assert "TRUNCATE" not in out
    assert out.index("DELETE FROM") < out.index("INSERT INTO public.rmp_reviews")
    assert "setval('public.rmp_reviews_id_seq'" in out
    assert "stats_cache" not in out
    assert "\\restrict abc123" in out and "\\unrestrict abc123" in out
    assert "tricky; has ''quoted'' text;\nand a newline" in out


def test_evidence_pulls_in_its_embeddings():
    assert restore_db.expand_tables({"evidence"}) == {"evidence", "evidence_embeddings"}

def test_delete_sql_orders_dependents_first_and_sets_lock_timeout():
    assert restore_db.delete_sql({"evidence", "evidence_embeddings", "stats_cache"}) == (
        "SET lock_timeout = '5s';\n"
        'DELETE FROM public."evidence_embeddings";\n'
        'DELETE FROM public."evidence";\n'
        'DELETE FROM public."stats_cache";\n')


def test_connection_helper_strips_password_into_env(monkeypatch):
    monkeypatch.delenv("PGPASSWORD", raising=False)
    dsn, env = restore_db.client_connection("postgresql://appuser:s3cr%40t@db.example.com:5432/appdb?sslmode=require")
    assert dsn == "postgresql://appuser@db.example.com:5432/appdb"
    assert env["PGPASSWORD"] == "s3cr@t"
    assert env["PGSSLMODE"] == "require"
    assert "PATH" in env or "Path" in env


def test_connection_helper_without_password(monkeypatch):
    monkeypatch.delenv("PGPASSWORD", raising=False)
    dsn, env = restore_db.client_connection("postgresql://appuser@db.example.com/appdb")
    assert dsn == "postgresql://appuser@db.example.com/appdb"
    assert "PGPASSWORD" not in env
    assert env["PGSSLMODE"] == "require"


def test_url_sslmode_cannot_override_the_required_ssl(monkeypatch):
    dsn, env = restore_db.client_connection(
        "postgresql://appuser@db.example.com/appdb?sslmode=disable&connect_timeout=10")
    assert dsn == "postgresql://appuser@db.example.com/appdb?connect_timeout=10"
    assert env["PGSSLMODE"] == "require"


def test_restore_passes_password_free_dsn_and_env_to_psql(tmp_path, monkeypatch):
    path = tmp_path / "d.sql.gz"
    path.write_bytes(gzip.compress(restore_db._FIXTURE_SQL.encode()))
    seen = {}

    class P:
        def __init__(self, cmd, **k):
            seen["cmd"], seen["env"] = cmd, k.get("env")
            self.stdin = type("S", (), {"write": lambda s, b: None, "close": lambda s: None})()
            self.returncode = 0

        def wait(self):
            return 0

    monkeypatch.setattr(restore_db.subprocess, "Popen", P)
    restore_db.restore("postgresql://u:pw@h/db", str(path), {"rmp_reviews"})
    assert not any("pw" in a for a in seen["cmd"])
    assert seen["env"]["PGPASSWORD"] == "pw" and seen["env"]["PGSSLMODE"] == "require"


def test_added_tables_note_names_what_was_added_and_why():
    assert restore_db.added_note({"evidence"}, {"evidence", "evidence_embeddings"}) == (
        "evidence_embeddings references evidence, so it is restored too.")
    assert restore_db.added_note({"stats_cache"}, {"stats_cache"}) is None


def test_pre_postgres_dumps_are_rejected(tmp_path):
    old = tmp_path / "old.sql.gz"
    with gzip.open(old, "wt", encoding="utf-8") as f:
        f.write("-- ratemyhusky NEW cluster backup\nDROP TABLE IF EXISTS rmp_reviews CASCADE;\n")
    with pytest.raises(ValueError, match="not a pg_dump"):
        restore_db.check_format(str(old))


def test_newest_dump_is_by_mtime_not_name(tmp_path):
    old = tmp_path / "ratemyhusky_new_20260602T001500Z.sql.gz"   # sorts last by name
    new = tmp_path / "ratemyhusky_20261010T120000Z.sql.gz"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    past = time.time() - 86400
    os.utime(old, (past, past))
    assert restore_db._newest_dump(str(tmp_path)) == str(new)


def test_corrupt_dump_kills_psql_instead_of_committing(tmp_path, monkeypatch):
    path = tmp_path / "corrupt.sql.gz"
    good = gzip.compress(restore_db._FIXTURE_SQL.encode() * 200)
    path.write_bytes(good[: len(good) // 2])          # truncated gzip stream

    class FakeStdin:
        def __init__(self):
            self.closed = False

        def write(self, s):
            pass

        def close(self):
            self.closed = True

    class FakeProc:
        def __init__(self, *a, **k):
            self.stdin = FakeStdin()
            self.killed_while_open = None
            self.returncode = 0
            procs.append(self)

        def kill(self):
            self.killed_while_open = not self.stdin.closed

        def wait(self):
            return self.returncode

    procs = []
    monkeypatch.setattr(restore_db.subprocess, "Popen", FakeProc)
    with pytest.raises((EOFError, OSError)):
        restore_db.restore("postgresql://x", str(path), {"rmp_reviews"})
    assert procs[0].killed_while_open is True


def test_confirm_label_for_hostnames_and_ips():
    assert restore_db.confirm("db.example.com", {"t"}, "d", input_fn=lambda _: "db") is True
    assert restore_db.confirm("db.example.com", {"t"}, "d", input_fn=lambda _: "yes") is False
    assert restore_db.confirm("129.80.1.2", {"t"}, "d", input_fn=lambda _: "129.80.1.2") is True
    assert restore_db.confirm("h", {"t"}, "d",
                              input_fn=lambda _: (_ for _ in ()).throw(AssertionError("prompted")),
                              assume_yes=True) is True


def test_filter_passes_carriage_returns_through_unchanged():
    lines = ["-- Data for Name: t; Type: TABLE DATA; Schema: public; Owner: -\r\n",
             "INSERT INTO public.t (c) VALUES\r\n",
             "\t('a\r\nb\rc');\r\n"]
    out = "".join(restore_db.filter_dump(lines, {"t"}))
    assert "'a\r\nb\rc'" in out
    assert out.endswith("INSERT INTO public.t (c) VALUES\r\n\t('a\r\nb\rc');\r\n")
    assert restore_db.dump_tables(lines) == ["t"]


def test_restore_sends_bytes_to_psql_without_newline_translation(tmp_path, monkeypatch):
    dump = ("-- PostgreSQL database dump\n\n"
            "-- Data for Name: t; Type: TABLE DATA; Schema: public; Owner: -\n\n"
            "INSERT INTO public.t (c) VALUES\n\t('a\r\nb\rc');\n\n"
            "-- PostgreSQL database dump complete\n")
    path = tmp_path / "crlf.sql.gz"
    path.write_bytes(gzip.compress(dump.encode("utf-8")))

    class FakeStdin:
        def __init__(self):
            self.data = b""
            self.closed = False

        def write(self, b):
            assert isinstance(b, bytes)
            self.data += b

        def close(self):
            self.closed = True

    class FakeProc:
        def __init__(self, *a, **k):
            self.stdin = FakeStdin()
            self.killed = False
            self.returncode = 0
            procs.append(self)

        def kill(self):
            self.killed = True

        def wait(self):
            return self.returncode

    procs = []
    monkeypatch.setattr(restore_db.subprocess, "Popen", FakeProc)
    restore_db.restore("postgresql://x", str(path), {"t"})
    sent = procs[0].stdin.data
    assert b"('a\r\nb\rc');\n" in sent
    assert b"\n" in sent and sent.count(b"\r") == 2      # only the two inside the literal
    assert b"VALUES\n\t(" in sent
    assert procs[0].stdin.closed and not procs[0].killed


def _fixture_dump(tmp_path):
    path = tmp_path / "d.sql.gz"
    path.write_bytes(gzip.compress(restore_db._FIXTURE_SQL.encode()))
    return path


def test_commit_is_written_last_not_left_to_end_of_input(tmp_path, monkeypatch):
    seen = {}

    class FakeStdin:
        data = b""

        def write(self, b):
            self.data += b

        def close(self):
            pass

    class FakeProc:
        def __init__(self, cmd, **k):
            seen["cmd"], self.stdin = cmd, FakeStdin()
            seen["stdin"] = self.stdin
            self.returncode = 0

        def wait(self):
            return 0

    monkeypatch.setattr(restore_db.subprocess, "Popen", FakeProc)
    restore_db.restore("postgresql://x", str(_fixture_dump(tmp_path)), {"rmp_reviews"})
    sent = seen["stdin"].data
    # --single-transaction would COMMIT on any end of input, including a cut-off stream.
    assert "--single-transaction" not in seen["cmd"]
    assert sent.startswith(b"BEGIN;\n") and sent.endswith(b"COMMIT;\n")
    assert sent.count(b"COMMIT") == 1


@pytest.mark.parametrize("closed_pipe", [BrokenPipeError(32, "Broken pipe"),
                                         OSError(22, "Invalid argument")])   # Windows
def test_psql_stopping_on_an_error_reports_the_rollback(tmp_path, monkeypatch, closed_pipe):
    class FakeStdin:
        def write(self, b):
            raise closed_pipe

        def close(self):
            pass

    class FakeProc:
        def __init__(self, *a, **k):
            self.stdin = FakeStdin()
            self.returncode = 3

        def kill(self):
            raise AssertionError("psql had already exited")

        def wait(self):
            return 3

    monkeypatch.setattr(restore_db.subprocess, "Popen", FakeProc)
    with pytest.raises(RuntimeError, match="rolled back"):
        restore_db.restore("postgresql://x", str(_fixture_dump(tmp_path)), {"rmp_reviews"})


def _run_main(monkeypatch, argv, in_schema):
    restored = {}
    monkeypatch.setenv("ORACLE_DATABASE_URL", "postgresql://u@db.example.com/appdb")
    monkeypatch.setattr(restore_db.sys, "argv", ["restore_db.py", *argv])
    monkeypatch.setattr(restore_db, "schema_tables", lambda url: in_schema)
    monkeypatch.setattr(restore_db, "restore", lambda url, path, tables: restored.update(tables=tables))
    restore_db.main()
    return restored.get("tables")


def test_all_skips_tables_the_target_schema_lacks(tmp_path, monkeypatch, capsys):
    dump = str(_fixture_dump(tmp_path))
    assert _run_main(monkeypatch, [dump, "--all", "--yes"], {"rmp_reviews"}) == {"rmp_reviews"}
    assert "Skipping stats_cache" in capsys.readouterr().out


def test_named_table_missing_from_the_target_schema_stops(tmp_path, monkeypatch):
    dump = str(_fixture_dump(tmp_path))
    with pytest.raises(SystemExit, match="Not in the target schema: stats_cache"):
        _run_main(monkeypatch, [dump, "--tables", "stats_cache", "--yes"], {"rmp_reviews"})
