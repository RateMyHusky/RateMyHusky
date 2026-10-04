"""One-time seed of `professors` + frozen `rmp_links` from today's matches (spec §5.2).

    python -m pipeline.seed                              # dry run: counts only
    python -m pipeline.seed --apply                      # write (ON CONFLICT DO NOTHING)
    python -m pipeline.seed --detail-out <scratch>/seed.csv

stdout carries counts only. --detail-out writes name-level rows and must point
outside the repository. Denied names are never written anywhere.
"""

import argparse
import csv
import pathlib
import sys

from denylist import is_denied_key
from prof_aliases import rmp_link_key

from .db import chunk_insert, connect, fetch_all
from .rmp_fields import rmp_id

REPO = pathlib.Path(__file__).resolve().parents[2]
PROFESSOR_FIELDS = ("slug", "name", "name_key", "department", "college",
                    "image_url", "focus_x", "focus_y")
LINK_FIELDS = ("rmp_id", "rmp_name", "rmp_department", "professor_url", "slug", "match_method")


def plan_seed(pages, catalog_rows, is_denied=is_denied_key):
    """(links, professors, counts, detail) from rmp_professors pages and
    professors_catalog rows. Pure. Slugs and names are copied, never computed."""
    by_key, ambiguous = {}, set()
    for row in catalog_rows:
        if row["name_key"] in by_key:
            ambiguous.add(row["name_key"])
        by_key[row["name_key"]] = row

    counts = dict.fromkeys(("pages", "links", "professors", "unmatched", "no_rmp_id",
                            "duplicate_rmp_id", "denied", "ambiguous"), 0)
    counts["pages"] = len(pages)
    denied_ids = {rmp_id(p["professor_url"]) for p in pages
                  if is_denied(rmp_link_key(p["name"])[0])} - {None}
    links, professors, detail, seen = [], {}, [], set()
    for page in pages:
        key, _ = rmp_link_key(page["name"])
        pid = rmp_id(page["professor_url"])
        if is_denied(key) or pid in denied_ids:
            counts["denied"] += 1
            continue
        if pid is None:
            counts["no_rmp_id"] += 1
            detail.append((page["name"], "no_rmp_id"))
            continue
        if key in ambiguous:
            counts["ambiguous"] += 1
            detail.append((page["name"], "ambiguous"))
            continue
        row = by_key.get(key)
        if row is None:
            counts["unmatched"] += 1
            detail.append((page["name"], "unmatched"))
            continue
        if pid in seen:
            counts["duplicate_rmp_id"] += 1
            continue
        seen.add(pid)
        links.append({"rmp_id": pid, "rmp_name": page["name"], "rmp_department": page["department"],
                      "professor_url": page["professor_url"], "slug": row["slug"],
                      "match_method": "frozen"})
        professors.setdefault(row["slug"], {f: row[f] for f in PROFESSOR_FIELDS})
    counts["links"], counts["professors"] = len(links), len(professors)
    return links, list(professors.values()), counts, detail


def _inside_repo(path):
    return REPO in pathlib.Path(path).resolve().parents


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--detail-out")
    args = ap.parse_args(argv)
    if args.detail_out and _inside_repo(args.detail_out):
        sys.exit("--detail-out must be outside the repository")

    conn = connect()
    pages = fetch_all(conn, "SELECT name, department, professor_url FROM rmp_professors "
                                 "ORDER BY name, department")
    catalog = fetch_all(conn, "SELECT slug, name, name_key, department, college, image_url, "
                              "focus_x, focus_y, professor_url FROM professors_catalog")
    links, professors, counts, detail = plan_seed(pages, catalog)
    counts["catalog_rows_with_rmp_url"] = sum(1 for r in catalog if r["professor_url"])
    for k, v in counts.items():
        print(f"{k}: {v}")
    if args.detail_out:
        with open(args.detail_out, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows([("rmp_name", "outcome"), *detail])
        print(f"detail rows written: {len(detail)}")
    if not args.apply:
        print("dry run: nothing written")
        return 0

    cur = conn.cursor()
    chunk_insert(cur, f"INSERT INTO professors ({', '.join(PROFESSOR_FIELDS)}) VALUES %s "
                      "ON CONFLICT (slug) DO NOTHING",
                 [tuple(p[f] for f in PROFESSOR_FIELDS) for p in professors])
    chunk_insert(cur, f"INSERT INTO rmp_links ({', '.join(LINK_FIELDS)}) VALUES %s "
                      "ON CONFLICT (rmp_id) DO NOTHING",
                 [tuple(l[f] for f in LINK_FIELDS) for l in links])
    conn.commit()
    drift = fetch_all(conn, "SELECT count(*) AS n FROM professors p LEFT JOIN professors_catalog c "
                            "ON c.slug = p.slug WHERE c.slug IS NULL OR c.name <> p.name")[0]["n"]
    print(f"seeded professors whose slug or name differs from the catalog: {drift}")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
