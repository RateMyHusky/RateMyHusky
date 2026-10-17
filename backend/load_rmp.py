"""
Load the RMP CSV exports into PostgreSQL.
Idempotent — safe to re-run. Pre-filters rows client-side so rows the DB
already has are never sent.

Run:  python backend/load_rmp.py <table> [<table> ...] [--replace]
      python backend/load_rmp.py all

Tables must be named: a bare run upserts nothing. Uploading every table from a
stale local CSV would re-insert reviews prune_rmp_reviews.py already removed.

The tables are defined in db/postgres/; this script never creates or alters them.
"""

import os, csv, sys, time
from dotenv import load_dotenv

import csv_store
from denylist import denied_hashes, is_denied

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DATABASE_URL = os.getenv("ORACLE_DATABASE_URL")

if not DATABASE_URL:
    sys.exit("Missing ORACLE_DATABASE_URL in backend/.env")

import psycopg2
from psycopg2.extras import execute_values

DATA_DIR = os.path.join(os.path.dirname(__file__), "Better_Scraper", "output_data")
BATCH_SIZE = 25000  # rows per INSERT; each batch commits on its own except under --replace


def get_connection(attempts=20):
    """Open a UTC session, retrying on DNS failure (the local resolver has
    flaked on the database host before)."""
    for i in range(attempts):
        try:
            return psycopg2.connect(DATABASE_URL, sslmode="require", options="-c timezone=UTC")
        except psycopg2.OperationalError as e:
            if "could not translate host name" not in str(e) or i == attempts - 1:
                raise
            time.sleep(2)


def fetch_existing_keys(conn, table: str, key_columns: list[str], key_query: str = None) -> set:
    """
    Fetch existing keys from the DB so we can skip them client-side.
    Uses key_query if provided (for lightweight proxy keys like DISTINCT course_url),
    otherwise builds a SELECT from key_columns.
    """
    try:
        sql = key_query or f"SELECT DISTINCT {', '.join(key_columns)} FROM {table}"
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        # Unwrap single-column tuples for simpler lookup
        if len(key_columns) == 1:
            return {row[0] for row in rows}
        return {row for row in rows}
    except Exception as e:
        conn.rollback()
        # Returning an empty set silently disables the client-side pre-filter and
        # re-sends the whole CSV through server-side conflict checks. Fail loud;
        # the weekly run self-heals next attempt.
        raise RuntimeError(f"fetch_existing_keys failed for {table}: {e}") from e


def _camel(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(p.title() for p in rest)


def _row_is_denied(row, raw, deny_name) -> bool:
    """Does this row belong to a professor on the denylist?

    Checks the transformed row and, independently, the raw CSV row under both
    naming conventions — because the transforms are not format-agnostic and a
    filter that silently stops matching is the worst failure mode this code has.
    a transform that reads camelCase keys against a snake_case export yields
    empty strings for every field; a name check against that output would pass
    every row through while reporting nothing wrong.

    Fail-safe on purpose: any spelling that matches drops the row. The cost of a
    false positive is one professor's rows missing from a load that can be re-run;
    the cost of a false negative is publishing data someone asked to have removed.
    """
    for source in (row, raw):
        if not source:
            continue
        for keys in (deny_name, tuple(_camel(c) for c in deny_name)):
            parts = [str(source.get(k) or "").strip() for k in keys]
            if any(parts) and is_denied(" ".join(p for p in parts if p)):
                return True
    return False


def upload_csv(conn, table: str, columns: list[str], csv_path: str,
               transform=None, on_conflict: str = "",
               key_columns: list[str] = None, existing_keys: set = None,
               deny_name: tuple = None, commit_batches: bool = True):
    if not os.path.exists(csv_path):
        print(f"  File not found: {csv_path}")
        return

    # csv_store, not open(): a big export may ship zipped, and DictReader
    # cannot open a .zip the way pandas can.
    with csv_store.open_text(csv_path) as f:
        reader = csv.DictReader(f)
        batch = []
        total = 0
        skipped = 0

        col_names = ", ".join(columns)
        insert_sql = f"INSERT INTO {table} ({col_names}) VALUES %s{' ' + on_conflict if on_conflict else ''}"

        # Find key column indices for client-side filtering
        key_indices = None
        single_key = False
        if key_columns and existing_keys:
            key_indices = [columns.index(k) for k in key_columns]
            single_key = len(key_columns) == 1

        # Data-deletion requests: drop the row before it is ever inserted.
        # `deny_name` names the post-transform columns holding the professor's
        # name; joined with a space, that is the same string precompute builds a
        # name_key from.
        denied_active = bool(deny_name) and bool(denied_hashes())
        denied_rows = 0

        for row in reader:
            raw = row
            if transform:
                row = transform(row)
            if row is None:
                continue
            if denied_active and _row_is_denied(row, raw, deny_name):
                denied_rows += 1
                continue
            values = tuple(row[col] for col in columns)

            # Skip rows that already exist in the DB rather than sending them for conflict checks
            if key_indices is not None and existing_keys:
                if single_key:
                    key = values[key_indices[0]]
                else:
                    key = tuple(values[i] for i in key_indices)
                if key in existing_keys:
                    skipped += 1
                    continue

            batch.append(values)

            if len(batch) >= BATCH_SIZE:
                with conn.cursor() as cur:
                    execute_values(cur, insert_sql, batch, page_size=BATCH_SIZE)
                if commit_batches:
                    conn.commit()
                total += len(batch)
                print(f"  Uploaded {total:,} new rows (skipped {skipped:,} existing)...", end="\r")
                batch = []

        if batch:
            with conn.cursor() as cur:
                execute_values(cur, insert_sql, batch, page_size=BATCH_SIZE)
            if commit_batches:
                conn.commit()
            total += len(batch)
    print(f"  Done: {total:,} rows inserted, {skipped:,} skipped (already in DB)."
          + (f" {denied_rows:,} withheld (denylist)." if denied_rows else ""))


# ──────────────────────────────────────────────
#  Table definitions & transforms
# ──────────────────────────────────────────────

TABLES = {
    "rmp_professors": {
        "columns": ["name", "department", "rating", "num_ratings", "would_take_again_pct", "level_of_difficulty", "professor_url"],
        "key_columns": ["name", "department"],
        "csv": "rmp_professors.csv",
        "deny_name": ("name",),
        "on_conflict": "ON CONFLICT (name, department) DO NOTHING",
        "transform": lambda row: {
            "name": row.get("name", ""),
            "department": row.get("department", ""),
            "rating": float(row["rating"]) if row.get("rating") else None,
            "num_ratings": int(row["num_ratings"]) if row.get("num_ratings") else None,
            "would_take_again_pct": row.get("would_take_again_pct", ""),
            "level_of_difficulty": float(row["level_of_difficulty"]) if row.get("level_of_difficulty") else None,
            "professor_url": row.get("professor_url", ""),
        },
    },
    "rmp_reviews": {
        "columns": ["professor_name", "department", "overall_rating", "course", "quality", "difficulty", "date", "tags", "attendance", "grade", "textbook", "online_class", "comment"],
        # Lightweight proxy: skip by (professor, course, date) — avoids fetching full comment text
        "key_columns": ["professor_name", "course", "date"],
        "key_query": "SELECT DISTINCT professor_name, course, date FROM rmp_reviews",
        "csv": "rmp_reviews.csv",
        "deny_name": ("professor_name",),
        "on_conflict": "ON CONFLICT (professor_name, course, date, comment) DO NOTHING",
        "transform": lambda row: {
            "professor_name": row.get("professor_name", ""),
            "department": row.get("department", ""),
            "overall_rating": float(row["overall_rating"]) if row.get("overall_rating") else None,
            "course": row.get("course", ""),
            "quality": float(row["quality"]) if row.get("quality") else None,
            "difficulty": float(row["difficulty"]) if row.get("difficulty") else None,
            "date": row.get("date", ""),
            "tags": row.get("tags", ""),
            "attendance": row.get("attendance", ""),
            "grade": row.get("grade", ""),
            "textbook": row.get("textbook", ""),
            "online_class": row.get("online_class", ""),
            "comment": row.get("comment", ""),
        },
    },
    "professor_photos": {
        "columns": ["name", "image_url", "focus_x", "focus_y", "source_page"],
        "key_columns": ["name", "source_page"],
        "csv": "professor_photos.csv",
        "deny_name": ("name",),
        "on_conflict": "ON CONFLICT (name, source_page) DO NOTHING",
        "transform": lambda row: {
            "name": row.get("name", ""),
            "image_url": row.get("image_url", ""),
            "focus_x": row.get("focus_x", "") or None,
            "focus_y": row.get("focus_y", "") or None,
            "source_page": row.get("source_page", ""),
        },
    },
}


# Full-replace is only safe for a table whose CSV is a complete snapshot of the
# source each run AND whose ids nothing else references. The photo CSV is a
# cumulative artifact — replacing from it would destroy data.
#
# rmp_reviews meets the snapshot half but fails the second: evidence.source_ref
# for RMP is the review's id (scraper/load_evidence.py, build_rmp_rows), so
# truncating orphans the RMP half of the RAG corpus and forces a re-embed, and
# the TRUNCATE would lock a table the site reads on every professor page for
# the whole reload. prune_rmp_reviews.py converges the table without either
# cost — use that instead.
REPLACE_ALLOWED = {"rmp_professors"}


def load_table(conn, table_name, csv_path, replace=False):
    """Load one table from its CSV.

    With replace, the TRUNCATE and the reload commit as one transaction: a failed
    reload rolls the TRUNCATE back, and nothing in the request path reads this
    table, so the lock it takes until COMMIT blocks no page.
    """
    conf = TABLES[table_name]
    if replace:
        if not os.path.exists(csv_path):
            sys.exit(f"--replace: {csv_path} missing; refusing to truncate {table_name}")
        print(f"  Truncating {table_name} for full replace (commits with the reload)...")
        try:
            with conn.cursor() as cur:
                cur.execute(f"TRUNCATE TABLE {table_name}")
            upload_csv(conn, table_name, conf["columns"], csv_path,
                       conf.get("transform"), conf.get("on_conflict", ""),
                       None, None, conf.get("deny_name"), commit_batches=False)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return

    key_columns = conf.get("key_columns")
    existing_keys = set()
    if key_columns:
        print("  Fetching existing keys for client-side filtering...")
        existing_keys = fetch_existing_keys(conn, table_name, key_columns, conf.get("key_query"))
        print(f"  Found {len(existing_keys):,} existing keys")
    upload_csv(conn, table_name, conf["columns"], csv_path,
               conf.get("transform"), conf.get("on_conflict", ""),
               key_columns, existing_keys, conf.get("deny_name"))


def main():
    args = sys.argv[1:]
    replace = "--replace" in args
    targets = [a for a in args if not a.startswith("--")]
    if not targets:
        # No default: "all" writes every table to prod, so it has to be asked for.
        sys.exit("usage: load_rmp.py <table> [<table> ...] [--replace] | all\n"
                 f"tables: {', '.join(TABLES)}")

    if targets == ["all"]:
        targets = list(TABLES.keys())

    if replace:
        bad = [t for t in targets if t not in REPLACE_ALLOWED]
        if bad:
            sys.exit(f"--replace only supported for {sorted(REPLACE_ALLOWED)}, got: {bad}")

    conn = get_connection()
    print("Connected to the database.")

    for table_name in targets:
        if table_name not in TABLES:
            print(f"Unknown table: {table_name}")
            continue
        csv_path = csv_store.resolve(DATA_DIR, TABLES[table_name]["csv"])
        print(f"\n{'='*50}\nUploading: {table_name}\n{'='*50}")
        start = time.time()
        load_table(conn, table_name, csv_path, replace=replace)
        print(f"  Time: {time.time() - start:.1f}s")

    conn.close()
    print("\nDone! All tables loaded.")


if __name__ == "__main__":
    main()
