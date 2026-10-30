"""Delete rows already loaded for professors on the denylist.

The loaders' filters govern the next write; they cannot reach what is already in
the database. A deletion request needs both — the filters so a refresh never
restores the professor, this so the data goes now.

Deletion order is forced by how the tables reference each other:

  1. resolve identity   every slug and name key is collected BEFORE anything is
                        deleted, because the catalog row is the handle the
                        slug-keyed tables are found by.
  2. evidence_embeddings then evidence   the embedding references the evidence
                        row; the other order leaves vectors joined to nothing.
  3. everything else, the Banner history included: a course page names its
     instructors from those rows, catalog row or not

Run with --dry-run first. It reports the same counts without deleting.

    python purge_denied.py --dry-run
    python purge_denied.py
"""

import argparse
import re
import sys

from denylist import denied_hashes, is_denied, is_denied_key, name_key

# Tables that reach a professor only through professor_slug — they carry no name
# and no name_key, so a slug is the only handle the purge has on them.
SLUG_TABLES = ("evidence", "reddit_mentions", "reddit_sentiment")


def name_to_slug(name):
    """precompute.name_to_slug, duplicated to stay import-light.

    precompute pulls in pandas and numpy; this module is a small operational
    script that should run anywhere psycopg does. test_denylist pins the two
    implementations together.
    """
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def find_targets(cur):
    """Everything the denylist matches, resolved to ids before anything is deleted.

    Returns (slugs, name_keys, review_ids). Matching happens in
    Python rather than SQL because the list holds hashes, not names — there is no
    WHERE clause that can express "sha256 of this column is in this set", and the
    alternative is shipping the plaintext names into the query the file
    deliberately avoids storing.
    """
    slugs, name_keys = set(), set()

    cur.execute("SELECT slug, name, name_key FROM professors_catalog")
    for slug, name, nk in cur.fetchall():
        if is_denied(name) or is_denied_key(nk):
            slugs.add(slug)
            if nk:
                name_keys.add(nk)

    # The pipeline's own professors table keeps (slug, name_key) for a denied
    # professor even after the read-model rebuild drops their catalog row, since
    # drop_denied only filters in memory. It is the one slug source that survives
    # when the professor also has no RMP reviews left to rebuild a name from.
    try:
        cur.execute("SELECT slug, name, name_key FROM professors")
        for slug, name, nk in cur.fetchall():
            if is_denied(name) or is_denied_key(nk):
                slugs.add(slug)
                if nk:
                    name_keys.add(nk)
    except Exception:
        # Absent on a database the pipeline never ran on. Same rollback reason
        # as the slug probe below.
        conn = getattr(cur, "connection", None)
        if conn is not None:
            conn.rollback()

    # The catalog is not enough on its own. Once precompute has run with the
    # denylist the professor has no catalog row at all, while their review rows
    # are still loaded — so the raw tables have to be searched by name too, or a
    # purge after a refresh would find nothing and report clean.
    #
    # name_key(), not a hand-built "first last": the column this is compared
    # against is written by precompute through the full normalization, so a key
    # assembled without the NFKD fold, the whitespace collapse and ALIAS_MAP
    # matches zero rows for any accented or double-spaced name — and the purge
    # then reports success having deleted nothing.
    cur.execute("SELECT DISTINCT professor_name, name_key FROM rmp_reviews")
    for professor_name, nk in cur.fetchall():
        if is_denied(professor_name) or is_denied_key(nk):
            name_keys.add(nk or name_key(professor_name))

    # rmp_reviews.name_key is backfilled by precompute, so every row the weekly
    # RMP load just wrote still has it NULL. The delete below keys on name_key,
    # which means a purge run between that load and precompute — the ordinary
    # case, since a request does not wait for the schedule — left them in place.
    # Collected as ids, the same way rmp_professors is handled below: it keeps
    # the plaintext name out of the SQL.
    review_ids = set()
    cur.execute("SELECT id, professor_name FROM rmp_reviews WHERE name_key IS NULL")
    for review_id, professor_name in cur.fetchall():
        if is_denied(professor_name):
            review_ids.add(review_id)

    # evidence, reddit_mentions and reddit_sentiment key on professor_slug and
    # nothing else, so once precompute has dropped the catalog row there is no
    # slug left to look them up by — `slugs` came back empty and every RAG row
    # the chat can still retrieve and quote survived, while the tool printed a
    # clean result. precompute derives the slug as name_to_slug(name_key), so the
    # raw-table name match above reconstructs it.
    #
    # Exact slug only, never a prefix: collisions are broken with -2, -3 suffixes
    # and those rows cannot be shown to belong to the denied professor. The
    # catalog remains authoritative whenever the row still exists; this only
    # fills the hole left after it is gone.
    if name_keys:
        bases = {name_to_slug(k) for k in name_keys}
        for table in SLUG_TABLES:
            try:
                cur.execute(f"SELECT DISTINCT professor_slug FROM {table}")
                found = cur.fetchall()
            except Exception:
                # Not deployed here — reddit_sentiment is absent on a database
                # that never ran the reddit loader, and the matching delete step
                # below skips for the same reason. Roll back before moving on:
                # psycopg2 aborts the entire transaction on any error, so
                # swallowing this bare would make every later statement fail with
                # "current transaction is aborted" and the purge would skip its
                # first real delete for an unrelated reason.
                conn = getattr(cur, "connection", None)
                if conn is not None:
                    conn.rollback()
                continue
            slugs.update(row[0] for row in found if row[0] in bases)

    return sorted(slugs), sorted(name_keys), sorted(review_ids)


def banner_keys(cur, slugs):
    """instructor_keys of a denied professor's Banner rows.

    A course page lists its instructors from banner_course_instructors and
    names one from instructor_name when no catalog row joins, so dropping the
    catalog row leaves the name, terms and class sizes on every course they
    taught. The matcher filters them from the next run; this removes what an
    earlier run wrote. A row matches by its own key, or by a slug already
    resolved as denied, which covers a Banner-only spelling the matcher aliased
    to them.
    """
    keys = set()
    for table, sql in (
            ("banner_course_instructors",
             "SELECT DISTINCT instructor_key, professor_slug FROM banner_course_instructors"),
            ("banner_unmatched",
             "SELECT DISTINCT instructor_key, NULL FROM banner_unmatched")):
        try:
            cur.execute(sql)
            found = cur.fetchall()
        except Exception:
            # Absent on a database the Banner matcher never ran on. Rolled back
            # for the same reason as the slug probe in find_targets.
            conn = getattr(cur, "connection", None)
            if conn is not None:
                conn.rollback()
            continue
        keys.update(key for key, slug in found
                    if slug in slugs or is_denied_key(key) or is_denied(key))
    return sorted(keys)


def purge(conn, dry_run=False):
    """Delete every row belonging to a denied professor. Returns per-table counts."""
    if not denied_hashes():
        print("Denylist is empty — nothing to purge.")
        return {}

    cur = conn.cursor()
    slugs, name_keys, review_ids = find_targets(cur)
    instructor_keys = banner_keys(cur, set(slugs))
    print(f"Matched {len(slugs)} catalog slugs, {len(name_keys)} name keys, "
          f"{len(review_ids)} un-keyed review rows, "
          f"{len(instructor_keys)} Banner instructor keys")
    if not (slugs or name_keys or review_ids or instructor_keys):
        print("Nothing to purge.")
        return {}

    # (label, sql, params) in dependency order. Counted with SELECT first so a
    # dry run reports exactly what the real run would remove.
    steps = []
    if slugs:
        steps.append((
            "evidence_embeddings",
            "DELETE FROM evidence_embeddings WHERE evidence_id IN "
            "(SELECT id FROM evidence WHERE professor_slug = ANY(%s))",
            "SELECT count(*) FROM evidence_embeddings WHERE evidence_id IN "
            "(SELECT id FROM evidence WHERE professor_slug = ANY(%s))",
            (slugs,)))
        steps.append((
            "evidence",
            "DELETE FROM evidence WHERE professor_slug = ANY(%s)",
            "SELECT count(*) FROM evidence WHERE professor_slug = ANY(%s)",
            (slugs,)))
        steps.append((
            "reddit_sentiment",
            "DELETE FROM reddit_sentiment WHERE professor_slug = ANY(%s)",
            "SELECT count(*) FROM reddit_sentiment WHERE professor_slug = ANY(%s)",
            (slugs,)))
        steps.append((
            "reddit_mentions",
            "DELETE FROM reddit_mentions WHERE professor_slug = ANY(%s)",
            "SELECT count(*) FROM reddit_mentions WHERE professor_slug = ANY(%s)",
            (slugs,)))
        # The "teaching now" chip on their page.
        steps.append((
            "professor_teaching",
            "DELETE FROM professor_teaching WHERE professor_slug = ANY(%s)",
            "SELECT count(*) FROM professor_teaching WHERE professor_slug = ANY(%s)",
            (slugs,)))
        steps.append((
            "professors_catalog",
            "DELETE FROM professors_catalog WHERE slug = ANY(%s)",
            "SELECT count(*) FROM professors_catalog WHERE slug = ANY(%s)",
            (slugs,)))
        # The pipeline's identity tables: without these a deletion request
        # leaves the name and the RMP name + URL behind.
        steps.append((
            "rmp_links",
            "DELETE FROM rmp_links WHERE slug = ANY(%s)",
            "SELECT count(*) FROM rmp_links WHERE slug = ANY(%s)",
            (slugs,)))
        steps.append((
            "professors",
            "DELETE FROM professors WHERE slug = ANY(%s)",
            "SELECT count(*) FROM professors WHERE slug = ANY(%s)",
            (slugs,)))
    if name_keys:
        # review tags (pipeline/review_tags.py). review_tags and review_tags_processed
        # find their rows through rmp_reviews, so they have to go before it
        steps.append((
            "professor_tags",
            "DELETE FROM professor_tags WHERE name_key = ANY(%s)",
            "SELECT count(*) FROM professor_tags WHERE name_key = ANY(%s)",
            (name_keys,)))
        for table in ("review_tags", "review_tags_processed"):
            steps.append((
                table,
                f"DELETE FROM {table} WHERE source = 'rmp' AND source_id IN "
                "(SELECT id FROM rmp_reviews WHERE name_key = ANY(%s))",
                f"SELECT count(*) FROM {table} WHERE source = 'rmp' AND source_id IN "
                "(SELECT id FROM rmp_reviews WHERE name_key = ANY(%s))",
                (name_keys,)))
        steps.append((
            "rmp_reviews",
            "DELETE FROM rmp_reviews WHERE name_key = ANY(%s)",
            "SELECT count(*) FROM rmp_reviews WHERE name_key = ANY(%s)",
            (name_keys,)))
    if review_ids:
        # The rows the step above cannot see, because their name_key is still
        # NULL. Separate step rather than an OR so the count printed beside each
        # label stays the count for that predicate.
        steps.append((
            "rmp_reviews (un-keyed)",
            "DELETE FROM rmp_reviews WHERE id = ANY(%s)",
            "SELECT count(*) FROM rmp_reviews WHERE id = ANY(%s)",
            (review_ids,)))

    if instructor_keys:
        steps.append((
            "banner_course_instructors",
            "DELETE FROM banner_course_instructors WHERE instructor_key = ANY(%s)",
            "SELECT count(*) FROM banner_course_instructors WHERE instructor_key = ANY(%s)",
            (instructor_keys,)))
        steps.append((
            "banner_unmatched",
            "DELETE FROM banner_unmatched WHERE instructor_key = ANY(%s)",
            "SELECT count(*) FROM banner_unmatched WHERE instructor_key = ANY(%s)",
            (instructor_keys,)))

    results = {}
    for label, delete_sql, count_sql, params in steps:
        try:
            cur.execute(count_sql, params)
            n = cur.fetchone()[0]
        except Exception as exc:
            conn.rollback()
            cur = conn.cursor()
            print(f"  {label:25s} skipped ({str(exc).splitlines()[0][:60]})")
            continue
        results[label] = n
        if n and not dry_run:
            cur.execute(delete_sql, params)
            conn.commit()
        print(f"  {label:25s} {n:>7,} rows" + (" (dry run)" if dry_run and n else ""))

    # rmp_professors keys on the display name, not name_key.
    try:
        cur.execute("SELECT id, name FROM rmp_professors")
        ids = [pid for pid, name in cur.fetchall() if is_denied(name)]
        results["rmp_professors"] = len(ids)
        if ids and not dry_run:
            cur.execute("DELETE FROM rmp_professors WHERE id = ANY(%s)", (ids,))
            conn.commit()
        print(f"  {'rmp_professors':25s} {len(ids):>7,} rows"
              + (" (dry run)" if dry_run and ids else ""))
    except Exception as exc:
        conn.rollback()
        print(f"  rmp_professors skipped ({str(exc).splitlines()[0][:60]})")

    total = sum(results.values())
    print(f"\n{'Would delete' if dry_run else 'Deleted'} {total:,} rows across "
          f"{len([k for k, v in results.items() if v])} tables")
    if dry_run:
        print("Dry run — nothing was deleted. Re-run without --dry-run to apply.")
    else:
        print("The loaders' filters keep them out of future refreshes; see denylist.py.")
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be deleted, delete nothing")
    args = parser.parse_args(argv)

    from load_rmp import get_connection
    conn = get_connection()
    try:
        purge(conn, dry_run=args.dry_run)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
