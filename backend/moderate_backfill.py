"""use moderation APi on existing comments.



Run:
    python backend/moderate_backfill.py                 # all targets
    python backend/moderate_backfill.py --table rmp_reviews
    python backend/moderate_backfill.py --limit 500     # sample it before committing
    python backend/moderate_backfill.py --dry-run       # score and print, write nothing
"""

import argparse
import os
import sys
import time
from collections import Counter

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moderation import score_texts, ModerationUnavailable, BATCH_SIZE  # noqa: E402

DATABASE_URL = os.getenv("NEW_CRDB_DATABASE_URL") or os.getenv("CRDB_DATABASE_URL")
if not DATABASE_URL:
    sys.exit("Missing NEW_CRDB_DATABASE_URL (or CRDB_DATABASE_URL) in backend/.env")

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402



TARGETS = [
    {"table": "rmp_reviews", "pk": "id", "text_col": "comment"},
    {"table": "reddit_text", "pk": "source_id", "text_col": "body"},
]

ADD_COLUMNS = """
    ALTER TABLE {table} ADD COLUMN IF NOT EXISTS mod_action TEXT;
    ALTER TABLE {table} ADD COLUMN IF NOT EXISTS mod_reason TEXT;
    ALTER TABLE {table} ADD COLUMN IF NOT EXISTS mod_checked_at TIMESTAMPTZ;
"""

ADD_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_{table}_mod_action
        ON {table} (mod_action) WHERE mod_action IS NOT NULL;
"""


def connect(attempts=5):
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return psycopg2.connect(DATABASE_URL, sslmode="require")
        except psycopg2.OperationalError as exc:
            if "could not translate host name" not in str(exc):
                raise
            last = str(exc)
            if attempt < attempts:
                print(f"  DNS lookup failed; retrying ({attempt}/{attempts})...")
                time.sleep(2)
    sys.exit(f"Could not resolve the hostname after {attempts} attempts.\n{last}")


def ensure_columns(conn, target):
    with conn.cursor() as cur:
        cur.execute(ADD_COLUMNS.format(table=target["table"]))
        cur.execute(ADD_INDEX.format(table=target["table"]))
    conn.commit()


def count_pending(conn, target):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {target['table']} "
            f"WHERE mod_checked_at IS NULL AND {target['text_col']} IS NOT NULL"
        )
        return cur.fetchone()[0]


def fetch_batch(conn, target, size):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {target['pk']}, {target['text_col']} FROM {target['table']} "
            f"WHERE mod_checked_at IS NULL AND {target['text_col']} IS NOT NULL "
            f"LIMIT %s",
            (size,),
        )
        return cur.fetchall()


def write_verdicts(conn, target, rows):
    """rows: [(pk, action, reason)]"""
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            f"UPDATE {target['table']} "
            f"SET mod_action = %s, mod_reason = %s, mod_checked_at = now() "
            f"WHERE {target['pk']} = %s",
            [(action, reason, pk) for pk, action, reason in rows],
            page_size=BATCH_SIZE,
        )
    conn.commit()


def run_target(conn, target, limit=None, dry_run=False):
    ensure_columns(conn, target)

    pending = count_pending(conn, target)
    if limit is not None:
        pending = min(pending, limit)
    print(f"\n{target['table']}: {pending} unscored comment(s)")
    if not pending:
        return Counter()

    tally = Counter()
    done = 0

    while done < pending:
        size = min(BATCH_SIZE, pending - done)
        batch = fetch_batch(conn, target, size)
        if not batch:
            break

        pks = [r[0] for r in batch]
        texts = [r[1] or "" for r in batch]

        try:
            verdicts = score_texts(texts)
        except ModerationUnavailable as exc:
            # stop rather than guess — everything past here stays unscored
            print(f"\n  moderation API unavailable: {exc}")
            print(f"  stopped after {done} row(s); the remainder stays unscored.")
            print("  re-run this script to resume.")
            raise SystemExit(1)

        rows = [(pk, v.action, v.reason) for pk, v in zip(pks, verdicts)]
        tally.update(v.action for v in verdicts)

        if dry_run:
            for (pk, action, reason), text in zip(rows, texts):
                if action != "allow":
                    print(f"  [{action}] {reason} :: {text[:110]!r}")
        else:
            write_verdicts(conn, target, rows)

        done += len(batch)
        print(f"  {done}/{pending}  "
              f"allow={tally['allow']} review={tally['review']} block={tally['block']}",
              end="\r", flush=True)

    print()
    return tally


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--table", help="only this table (default: all targets)")
    ap.add_argument("--limit", type=int, help="stop after N rows per table")
    ap.add_argument("--dry-run", action="store_true",
                    help="score and print non-clean rows, write nothing")
    args = ap.parse_args()

    targets = TARGETS
    if args.table:
        targets = [t for t in TARGETS if t["table"] == args.table]
        if not targets:
            sys.exit(f"Unknown table {args.table!r}. "
                     f"Known: {', '.join(t['table'] for t in TARGETS)}")

    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("Missing OPENAI_API_KEY in backend/.env - moderation cannot score.")

    conn = connect()
    total = Counter()
    try:
        for target in targets:
            total.update(run_target(conn, target, limit=args.limit, dry_run=args.dry_run))
    finally:
        conn.close()

    scored = sum(total.values())
    print(f"\nScored {scored} comment(s): "
          f"{total['allow']} allow, {total['review']} review, {total['block']} block")
    if args.dry_run:
        print("Dry run - nothing was written.")
    elif scored:
        print("Set MODERATION_ENFORCE=true once every target is fully scored.")


if __name__ == "__main__":
    main()
