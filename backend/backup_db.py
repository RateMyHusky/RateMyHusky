"""
Back up the PostgreSQL database to a gzipped, data-only SQL dump.

The schema is not in the dump: it lives in db/postgres/, and restore_db.py loads
rows back into that existing schema. Rows are INSERTs with explicit column
lists (pg_dump --column-inserts), which scraper/match_professors.py parses, and
pg_dump writes each identity column's setval so ids resume correctly.

Needs the PostgreSQL 16 client tools (pg_dump) on PATH. Reads ORACLE_DATABASE_URL
from backend/.env.

Run:  python backend/backup_db.py
Output: backend/backups/ratemyhusky_<UTC>Z.sql.gz (readable by its owner only)
"""

import datetime
import gzip
import os
import re
import shutil
import subprocess
import sys

import psycopg2
from dotenv import load_dotenv

from restore_db import client_connection

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BACKUP_DIR = os.path.join(os.path.dirname(__file__), "backups")
PG_DUMP_ARGS = ["--data-only", "--column-inserts", "--rows-per-insert=500",
                "--no-owner", "--no-privileges"]
CHUNK = 1 << 20


def pg_dump_major(version_text):
    """16 from 'pg_dump (PostgreSQL) 16.4', or None if it does not parse."""
    m = re.search(r"\(PostgreSQL\)\s+(\d+)", version_text or "")
    return int(m.group(1)) if m else None


def server_major(url):
    """The server's major version (16 for 16.10)."""
    conn = psycopg2.connect(url, sslmode="require", connect_timeout=15)
    try:
        cur = conn.cursor()
        cur.execute("SHOW server_version_num")
        return int(cur.fetchone()[0]) // 10000
    finally:
        conn.close()


def require_matching_pg_dump(server_major_version, which=shutil.which, run=subprocess.run):
    """pg_dump's major must equal the server's: a newer pg_dump writes settings
    (e.g. transaction_timeout) that an older server rejects on restore."""
    path = which("pg_dump")
    if not path:
        sys.exit("pg_dump not found on PATH. Install the PostgreSQL 16 client tools (README, Backups).")
    out = run([path, "--version"], capture_output=True, text=True, check=True).stdout
    major = pg_dump_major(out)
    if major != server_major_version:
        sys.exit(f"pg_dump is version {major} but the server is version {server_major_version}; "
                 f"install the PostgreSQL {server_major_version} client tools so the dump can be restored.")
    return path


def backup_path(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return os.path.join(BACKUP_DIR, f"ratemyhusky_{now.strftime('%Y%m%dT%H%M%SZ')}.sql.gz")


def dump(url, path, pg_dump="pg_dump"):
    """Stream pg_dump's output into a gzip file only its owner can read."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    dsn, env = client_connection(url)
    proc = subprocess.Popen([pg_dump, f"--dbname={dsn}", *PG_DUMP_ARGS], stdout=subprocess.PIPE, env=env)
    try:
        with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb") as gz:
            shutil.copyfileobj(proc.stdout, gz, CHUNK)
    except BaseException:
        # A partial file would become the newest dump restore_db picks by default.
        proc.kill()
        proc.wait()
        os.remove(path)
        raise
    proc.stdout.close()
    if proc.wait() != 0:
        os.remove(path)
        raise RuntimeError(f"pg_dump exited with status {proc.returncode}; partial dump removed.")
    return path


def main():
    url = os.getenv("ORACLE_DATABASE_URL")
    if not url:
        sys.exit("Missing ORACLE_DATABASE_URL in backend/.env")
    path = dump(url, backup_path(), require_matching_pg_dump(server_major(url)))
    print(f"Backup complete: {path} ({os.path.getsize(path) / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
