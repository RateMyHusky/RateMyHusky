"""Database plumbing for the pipeline: connect, bulk insert, build-then-swap."""

import os
import time

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor, execute_values

load_dotenv()


def database_url():
    # The local .env's CRDB_DATABASE_URL is the retired cluster; the new one wins.
    url = os.getenv("NEW_CRDB_DATABASE_URL") or os.getenv("CRDB_DATABASE_URL")
    if not url:
        raise RuntimeError("NEW_CRDB_DATABASE_URL (or CRDB_DATABASE_URL) is required")
    return url


def connect(attempts=20):
    """The local resolver flakes on *.cockroachlabs.cloud; retry on DNS failure."""
    last = None
    for i in range(1, attempts + 1):
        try:
            return psycopg2.connect(database_url(), sslmode="require")
        except psycopg2.OperationalError as e:
            if "could not translate host name" not in str(e):
                raise
            last = str(e)
            print(f"  DNS lookup flaked; retrying ({i}/{attempts})...")
            time.sleep(3)
    raise RuntimeError(f"Could not resolve CRDB host after {attempts} attempts.\n{last}")


def chunk_insert(cur, sql, rows, page_size=5000):
    for i in range(0, len(rows), page_size):
        execute_values(cur, sql, rows[i:i + page_size])


def swap_in(conn, table):
    """Replace <table> with the freshly-built <table>_new without a
    missing-table window.

    CRDB v25.1+ autocommits before every DDL (autocommit_before_ddl=on), so a
    DROP+CREATE+INSERT rebuild exposes live readers to a missing/empty table and
    a crash mid-rebuild leaves no table at all. Instead: build into _new, then
    swap via two renames committed together (renames are metadata-only and
    allowed transactionally once the DDL autocommit is off for the session).
    A stray _old/_new from a crashed run is cleaned by the next run's DROPs.
    """
    cur = conn.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {table}_old")
    conn.commit()
    try:
        cur.execute("SET autocommit_before_ddl = off")
        conn.commit()
        cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,)
        )
        if cur.fetchone():
            cur.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
        cur.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
        conn.commit()  # both renames land together — no missing-table window
    except Exception as e:
        conn.rollback()
        cur = conn.cursor()
        # Fallback: per-statement renames (millisecond window, still crash-safe
        # — worst case is a stray _old plus one rename to redo, never a
        # missing table for more than an instant).
        print(f"  swap_in: transactional swap failed for {table} ({e}); using per-statement renames")
        cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,)
        )
        if cur.fetchone():
            cur.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
            conn.commit()
        cur.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
        conn.commit()
    finally:
        try:
            cur.execute("RESET autocommit_before_ddl")
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  swap_in: RESET autocommit_before_ddl failed for {table} ({e}); "
                  "later DDL in this run may fail")
    cur.execute(f"DROP TABLE IF EXISTS {table}_old")
    conn.commit()
    cur.close()


def fetch_all(conn, sql, params=None):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()
