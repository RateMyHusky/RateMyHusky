"""backup_db: pg_dump version gate and file naming."""

import datetime
import io

import pytest

import backup_db


def test_pg_dump_major_parses_real_version_strings():
    assert backup_db.pg_dump_major("pg_dump (PostgreSQL) 16.4") == 16
    assert backup_db.pg_dump_major("pg_dump (PostgreSQL) 16.10 (Ubuntu 16.10-0ubuntu0.24.04.1)") == 16
    assert backup_db.pg_dump_major("pg_dump (PostgreSQL) 15.8") == 15
    assert backup_db.pg_dump_major("garbage") is None


def _run_returning(version_line):
    class Out:
        stdout = version_line

    return lambda *a, **k: Out()


def test_require_matching_pg_dump_rejects_missing_and_mismatched_versions():
    with pytest.raises(SystemExit, match="not found"):
        backup_db.require_matching_pg_dump(16, which=lambda name: None)
    for line, found in (("pg_dump (PostgreSQL) 17.2\n", "17"), ("pg_dump (PostgreSQL) 15.8\n", "15")):
        with pytest.raises(SystemExit) as e:
            backup_db.require_matching_pg_dump(16, which=lambda name: "/usr/bin/pg_dump",
                                               run=_run_returning(line))
        msg = str(e.value)
        assert found in msg and "16" in msg and "install" in msg.lower()


def test_require_matching_pg_dump_accepts_the_server_major():
    assert backup_db.require_matching_pg_dump(
        16, which=lambda name: "/usr/bin/pg_dump",
        run=_run_returning("pg_dump (PostgreSQL) 16.10\n")) == "/usr/bin/pg_dump"


def test_server_major_reads_server_version_num(monkeypatch):
    seen = {}

    class Cur:
        def execute(self, q):
            seen["q"] = q

        def fetchone(self):
            return ("160010",)

        def close(self):
            pass

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            pass

    def connect(url, **kw):
        seen["url"], seen["kw"] = url, kw
        return Conn()

    monkeypatch.setattr(backup_db.psycopg2, "connect", connect)
    assert backup_db.server_major("postgresql://x") == 16
    assert seen["q"] == "SHOW server_version_num"
    assert seen["kw"]["sslmode"] == "require" and seen["kw"]["connect_timeout"] == 15


def test_dump_passes_password_free_dsn_and_env(tmp_path, monkeypatch):
    seen = {}

    class P:
        def __init__(self, cmd, **k):
            seen["cmd"], seen["env"] = cmd, k.get("env")
            self.stdout = io.BytesIO(b"x")

        def wait(self):
            return 0

    monkeypatch.setattr(backup_db.subprocess, "Popen", P)
    backup_db.dump("postgresql://u:pw@h/db", str(tmp_path / "b.sql.gz"))
    assert not any("pw" in a for a in seen["cmd"])
    assert seen["env"]["PGPASSWORD"] == "pw" and seen["env"]["PGSSLMODE"] == "require"


def test_failed_write_removes_the_partial_dump(tmp_path, monkeypatch):
    class Stdout(io.BytesIO):
        def read(self, *a):
            raise OSError("No space left on device")

    class P:
        def __init__(self, cmd, **k):
            self.stdout = Stdout()
            self.killed = False
            procs.append(self)

        def kill(self):
            self.killed = True

        def wait(self):
            return -9

    procs = []
    monkeypatch.setattr(backup_db.subprocess, "Popen", P)
    path = tmp_path / "b.sql.gz"
    with pytest.raises(OSError, match="No space"):
        backup_db.dump("postgresql://x", str(path))
    assert not path.exists() and procs[0].killed


def test_backup_path_is_timestamped_in_utc():
    now = datetime.datetime(2026, 10, 10, 12, 0, 0, tzinfo=datetime.timezone.utc)
    assert backup_db.backup_path(now).endswith("ratemyhusky_20261010T120000Z.sql.gz")
