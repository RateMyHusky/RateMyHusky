"""backup_db -> modify -> restore_db brings rows back and ids keep counting."""

import shutil
import subprocess

import pytest

import backup_db
import restore_db
from tests.pg.pgutil import rows, scalar, truncate


def _client_ok(tool):
    path = shutil.which(tool)
    if not path:
        return False
    out = subprocess.run([path, "--version"], capture_output=True, text=True).stdout
    return (backup_db.pg_dump_major(out) or 0) >= 16


pytestmark = pytest.mark.skipif(not (_client_ok("pg_dump") and _client_ok("psql")),
                                reason="PostgreSQL 16 client tools not on PATH")


def test_backup_then_restore_round_trips_rows_and_identity(pg, pg_url, tmp_path):
    truncate(pg, "stats_cache", "bookmarks")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO stats_cache (key, value) VALUES ('professors', 1)")
        cur.execute("INSERT INTO bookmarks (user_sub, item_type, item_key) VALUES ('u1', 'professor', 'alice-smith')")
    pg.commit()

    path = backup_db.dump(pg_url, str(tmp_path / "ratemyhusky_test.sql.gz"))
    restore_db.check_format(path)

    with pg.cursor() as cur:
        cur.execute("UPDATE stats_cache SET value = 999 WHERE key = 'professors'")
        cur.execute("DELETE FROM bookmarks")
        cur.execute("INSERT INTO bookmarks (user_sub, item_type, item_key) VALUES ('u2', 'course', 'CS2500')")
    pg.commit()

    restore_db.restore(pg_url, path, {"stats_cache", "bookmarks"})

    assert scalar(pg, "SELECT value FROM stats_cache WHERE key = 'professors'") == 1
    assert [r["user_sub"] for r in rows(pg, "SELECT user_sub FROM bookmarks")] == ["u1"]
    restored_max = scalar(pg, "SELECT max(id) FROM bookmarks")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO bookmarks (user_sub, item_type, item_key) "
                    "VALUES ('u3', 'course', 'CS2500') RETURNING id")
        new_id = cur.fetchone()[0]
    pg.commit()
    # setval restored the counter: the next id is exactly the restored max + 1.
    assert new_id == restored_max + 1
