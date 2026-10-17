"""Database plumbing for the pipeline: connect, bulk insert, fetch."""

import os
import time

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor, execute_values

load_dotenv()


def database_url():
    url = os.getenv("ORACLE_DATABASE_URL")
    if not url:
        raise RuntimeError("ORACLE_DATABASE_URL is required")
    return url


def connect(attempts=20):
    """Open a UTC session, retrying on DNS failure (the local resolver has
    flaked on the database host before)."""
    last = None
    for i in range(1, attempts + 1):
        try:
            return psycopg2.connect(database_url(), sslmode="require", options="-c timezone=UTC")
        except psycopg2.OperationalError as e:
            if "could not translate host name" not in str(e):
                raise
            last = str(e)
            print(f"  DNS lookup flaked; retrying ({i}/{attempts})...")
            time.sleep(3)
    raise RuntimeError(f"Could not resolve the database host after {attempts} attempts.\n{last}")


def chunk_insert(cur, sql, rows, page_size=5000):
    for i in range(0, len(rows), page_size):
        execute_values(cur, sql, rows[i:i + page_size])


def fetch_all(conn, sql, params=None):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()
