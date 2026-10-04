"""Tag rmp_reviews with teaching-style tags and roll them up per professor.

    python -m pipeline.review_tags --limit 50 --dry-run   # print tags, write nothing
    python -m pipeline.review_tags                         # tag everything not done yet
    python -m pipeline.review_tags --rebuild               # just recount professor_tags

Runs on a dev machine, not Railway — the local model is too heavy for that box.
The site only reads professor_tags. Needs the tables from python -m pipeline.schema --apply.

Hidden reviews (moderation.sql_filter()) are skipped and never counted.
"""

import argparse

from psycopg2.extras import execute_values

import moderation
from tag_extractor import extract_tags, might_have_tags, structured_tags

from .db import connect, fetch_all

BATCH_SIZE = 15     # reviews per model call
MAX_CHARS = 1000    # long comments get cut, tags are almost always early anyway


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


def _write(conn, tag_rows, done_ids):
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
    """Writes review_tags + marks rows processed. Returns name_keys touched."""
    touched = set()
    candidates = [r for r in rows if might_have_tags(r["comment"])]
    rest = [r for r in rows if not might_have_tags(r["comment"])]
    print(f"  {len(rows):,} unprocessed, {len(candidates):,} go to the model")

    # No comment signal: structured fields only, then done.
    tag_rows = [("rmp", r["id"], t) for r in rest for t in structured_tags(r)]
    touched |= {r["name_key"] for r in rest if structured_tags(r)}
    if not dry_run:
        _write(conn, tag_rows, [r["id"] for r in rest])

    for i in range(0, len(candidates), BATCH_SIZE):
        chunk = candidates[i:i + BATCH_SIZE]
        payload = [{"id": str(r["id"]), "text": r["comment"][:MAX_CHARS]} for r in chunk]
        results = extract_tags(payload)
        if results is None:
            continue  # call failed, leave unprocessed so it retries next run

        tag_rows = []
        for r in chunk:
            tags = structured_tags(r) | set(results.get(str(r["id"]), []))
            if tags:
                touched.add(r["name_key"])
                tag_rows += [("rmp", r["id"], t) for t in sorted(tags)]
                if dry_run:
                    print(f"    {sorted(tags)}  <- {r['comment'][:80]!r}")

        if not dry_run:
            _write(conn, tag_rows, [r["id"] for r in chunk])
        print(f"    batch {i // BATCH_SIZE + 1}: {len(results)}/{len(chunk)} tagged by the model")

    return touched


_COUNTS_SQL = """
    SELECT r.name_key, rt.tag, COUNT(*)
    FROM review_tags rt
    JOIN (SELECT id, name_key FROM rmp_reviews WHERE true{filt}) r
      ON rt.source = 'rmp' AND rt.source_id = r.id
    {where}
    GROUP BY r.name_key, rt.tag
"""


def rebuild_professor_tags(conn, name_keys=None):
    """Recount professor_tags. Pass name_keys to only redo those professors.
    DELETE + INSERT commit together, so readers never see it half-built."""
    cur = conn.cursor()
    filt = moderation.sql_filter()
    if name_keys:
        keys = tuple(name_keys)
        cur.execute("DELETE FROM professor_tags WHERE name_key IN %s", (keys,))
        sql = _COUNTS_SQL.format(filt=filt, where="WHERE r.name_key IN %s")
        cur.execute(f"INSERT INTO professor_tags (name_key, tag, review_count) {sql}", (keys,))
    else:
        cur.execute("DELETE FROM professor_tags")
        sql = _COUNTS_SQL.format(filt=filt, where="")
        cur.execute(f"INSERT INTO professor_tags (name_key, tag, review_count) {sql}")
    conn.commit()
    cur.close()


def show_field_values(conn):
    """So you can check structured_tags() matches what RMP actually stores."""
    for col in ("attendance", "textbook"):
        rows = fetch_all(conn, f"SELECT {col} AS v, COUNT(*) AS n FROM rmp_reviews "
                               f"GROUP BY {col} ORDER BY n DESC LIMIT 8")
        print(f"  {col}: " + ", ".join(f"{r['v']!r}={r['n']}" for r in rows))
    rows = fetch_all(conn, "SELECT tags FROM rmp_reviews WHERE tags IS NOT NULL AND tags != '' LIMIT 3")
    print("  tags samples: " + " | ".join(repr(r["tags"]) for r in rows))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200_000, help="max reviews this run")
    ap.add_argument("--dry-run", action="store_true", help="print tags, write nothing")
    ap.add_argument("--rebuild", action="store_true", help="just recount professor_tags")
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
        print("dry run: nothing written")
    elif touched:
        rebuild_professor_tags(conn, touched)
        print(f"professor_tags updated for {len(touched):,} professors")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
