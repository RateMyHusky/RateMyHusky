"""Tags rmp_reviews and counts tags per professor into professor_tags.

    python -m pipeline.review_tags --limit 50 --dry-run
    python -m pipeline.review_tags
    python -m pipeline.review_tags --rebuild    # just redo the counts

Run this locally, not on Railway (the model is too heavy for it).
Needs the tables from python -m pipeline.schema --apply first.
"""

import argparse

from psycopg2.extras import execute_values

import moderation
from tag_extractor import extract_tags, might_have_tags, structured_tags

from .db import connect, fetch_all

BATCH_SIZE = 15
MAX_CHARS = 1000


def fetch_unprocessed(conn, limit):
    return fetch_all(conn, f"""
        SELECT id, name_key, comment, attendance, textbook, tags
        FROM rmp_reviews
        WHERE true{moderation.sql_filter()}
          AND name_key IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM review_tags_processed p
              WHERE p.source = 'rmp' AND p.source_id = rmp_reviews.id
          )
        LIMIT %s
    """, (limit,))


def save(conn, tag_rows, done_ids):
    cur = conn.cursor()
    if tag_rows:
        execute_values(cur, "INSERT INTO review_tags (source, source_id, tag) VALUES %s "
                            "ON CONFLICT DO NOTHING", tag_rows)
    if done_ids:
        execute_values(cur, "INSERT INTO review_tags_processed (source, source_id) VALUES %s "
                            "ON CONFLICT DO NOTHING", [("rmp", i) for i in done_ids])
    conn.commit()
    cur.close()


def tag_reviews(conn, rows, dry_run=False):
    touched = set()  # name_keys whose counts need updating
    to_model = [r for r in rows if might_have_tags(r["comment"])]
    skip_model = [r for r in rows if not might_have_tags(r["comment"])]
    print(f"  {len(rows):,} reviews, {len(to_model):,} going to the model")

    # these only get the RMP field tags
    tag_rows = []
    for r in skip_model:
        tags = structured_tags(r)
        if tags:
            touched.add(r["name_key"])
            tag_rows += [("rmp", r["id"], t) for t in tags]
    if not dry_run:
        save(conn, tag_rows, [r["id"] for r in skip_model])

    for i in range(0, len(to_model), BATCH_SIZE):
        batch = to_model[i:i + BATCH_SIZE]
        payload = [{"id": str(r["id"]), "text": r["comment"][:MAX_CHARS]} for r in batch]
        results = extract_tags(payload)
        if results is None:
            continue  # don't mark these done, retry next time

        tag_rows = []
        for r in batch:
            tags = structured_tags(r) | set(results.get(str(r["id"]), []))
            if not tags:
                continue
            touched.add(r["name_key"])
            tag_rows += [("rmp", r["id"], t) for t in sorted(tags)]
            if dry_run:
                print(f"    {sorted(tags)}  <- {r['comment'][:80]!r}")

        if not dry_run:
            save(conn, tag_rows, [r["id"] for r in batch])
        print(f"    batch {i // BATCH_SIZE + 1}: model tagged {len(results)}/{len(batch)}")

    return touched


COUNTS_SQL = """
    SELECT r.name_key, rt.tag, COUNT(*)
    FROM review_tags rt
    JOIN (SELECT id, name_key FROM rmp_reviews WHERE true{filt}) r
      ON rt.source = 'rmp' AND rt.source_id = r.id
    {where}
    GROUP BY r.name_key, rt.tag
"""


def rebuild_professor_tags(conn, name_keys=None):
    # delete + insert in one commit so the site never sees it half done
    cur = conn.cursor()
    filt = moderation.sql_filter()
    if name_keys:
        keys = tuple(name_keys)
        cur.execute("DELETE FROM professor_tags WHERE name_key IN %s", (keys,))
        sql = COUNTS_SQL.format(filt=filt, where="WHERE r.name_key IN %s")
        cur.execute(f"INSERT INTO professor_tags (name_key, tag, review_count) {sql}", (keys,))
    else:
        cur.execute("DELETE FROM professor_tags")
        sql = COUNTS_SQL.format(filt=filt, where="")
        cur.execute(f"INSERT INTO professor_tags (name_key, tag, review_count) {sql}")
    conn.commit()
    cur.close()


def show_field_values(conn):
    # to check what RMP actually stores for these before trusting structured_tags
    for col in ("attendance", "textbook"):
        rows = fetch_all(conn, f"SELECT {col} AS v, COUNT(*) AS n FROM rmp_reviews "
                               f"GROUP BY {col} ORDER BY n DESC LIMIT 8")
        print(f"  {col}: " + ", ".join(f"{r['v']!r}={r['n']}" for r in rows))
    rows = fetch_all(conn, "SELECT tags FROM rmp_reviews WHERE tags IS NOT NULL AND tags != '' LIMIT 3")
    print("  tags examples: " + " | ".join(repr(r["tags"]) for r in rows))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200_000)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args(argv)
    conn = connect()

    if args.rebuild:
        rebuild_professor_tags(conn)
        print("professor_tags rebuilt")
        return 0

    print(f"moderation filter: {'on' if moderation.enforcing() else 'off'}")
    if args.dry_run:
        show_field_values(conn)

    touched = tag_reviews(conn, fetch_unprocessed(conn, args.limit), args.dry_run)

    if args.dry_run:
        print("dry run, nothing written")
    elif touched:
        rebuild_professor_tags(conn, touched)
        print(f"updated professor_tags for {len(touched):,} professors")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
