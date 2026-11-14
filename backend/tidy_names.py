"""Tidy stored professor display names with pipeline.names.tidy_name.

Unescapes HTML entities, collapses whitespace and recases all-caps or
all-lowercase names. Only professors.name is written: slugs, name_key and
rmp_links.rmp_name stay as they are, and professors_catalog and the Banner
tables are never touched.

Run with --dry-run first. It lists the same changes without writing them.

    python tidy_names.py --dry-run
    python tidy_names.py
"""

import argparse
import sys

from pipeline.names import tidy_name


def tidy(conn, dry_run=False):
    """Rewrite names that tidy_name changes. Returns (slug, old, new), sorted by slug."""
    cur = conn.cursor()
    cur.execute("SELECT slug, name FROM professors ORDER BY slug")
    changes = [(slug, name, new) for slug, name in cur.fetchall()
               for new in [tidy_name(name)] if new != name]
    for slug, old, new in changes:
        print(f"{slug}: {old} -> {new}")
    print(f"{len(changes)} names {'would change' if dry_run else 'changed'}")
    if dry_run:
        conn.rollback()
        return changes
    for slug, old, new in changes:
        cur.execute("UPDATE professors SET name = %s WHERE slug = %s AND name = %s",
                    (new, slug, old))
    conn.commit()
    return changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="List the changes, write nothing")
    args = parser.parse_args(argv)

    from load_rmp import get_connection
    conn = get_connection()
    try:
        tidy(conn, dry_run=args.dry_run)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
