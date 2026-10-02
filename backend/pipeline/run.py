"""Rebuild everything the site reads, from the database alone (spec §5.3).

    python -m pipeline.run --dry-run   # compute + verify, write nothing
    python -m pipeline.run             # write (back up first: python backup_db.py)

stdout carries counts only.
"""

import argparse

import moderation

from . import course_codes, name_keys, read_models, roster, summaries
from .blend import blend
from .db import connect, fetch_all
from .rmp_fields import rmp_id


def _print(label, counts):
    print(f"{label}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    conn = connect()

    pages = fetch_all(conn, "SELECT name, department, rating, num_ratings, would_take_again_pct, "
                            "level_of_difficulty, professor_url FROM rmp_professors")
    links = fetch_all(conn, "SELECT rmp_id, rmp_name, rmp_department, professor_url, slug, "
                            "match_method FROM rmp_links")
    if not links:
        print("rmp_links is empty: run python -m pipeline.seed --apply first")
        return 1
    professors = fetch_all(conn, "SELECT slug, name, name_key, department, college, image_url, "
                                 "focus_x, focus_y FROM professors")

    catalog_courses = fetch_all(conn, "SELECT code, name, department, subject, search_text, is_placeholder "
                                      "FROM catalog_courses")

    new_links, new_professors, counts = roster.resolve_roster(pages, links, professors)
    _print("roster", counts)
    links, professors = links + new_links, professors + new_professors
    professors, links = read_models.drop_denied(professors, links)

    valid = {c["code"] for c in catalog_courses}
    print(f"moderation filter: {'on' if moderation.enforcing() else 'off'}")
    reviews = fetch_all(conn, "SELECT id, professor_name, department, name_key, course, quality, "
                              f"difficulty, grade, comment, (true{moderation.sql_filter()}) AS visible "
                              "FROM rmp_reviews")
    pairs = course_codes.plan_codes(reviews, valid)
    for r, (_, code) in zip(reviews, pairs):
        r["course_code"] = code
    print(f"course codes: reviews={len(pairs)}, with_code={sum(1 for _, c in pairs if c)}")

    slug_by_id = {l["rmp_id"]: l["slug"] for l in links}
    linked_pages, page_slug = [], {}
    for p in pages:
        slug = slug_by_id.get(rmp_id(p["professor_url"]))
        if slug:
            linked_pages.append({**p, "rmp_id": rmp_id(p["professor_url"]), "slug": slug})
            page_slug[(p["name"], p["department"])] = slug
    name_counts = {}
    for p in professors:
        name_counts[p["name_key"]] = name_counts.get(p["name_key"], 0) + 1
    name_key_slug = {p["name_key"]: p["slug"] for p in professors if name_counts[p["name_key"]] == 1}
    key_pairs = name_keys.plan_name_keys(reviews, page_slug, {p["slug"]: p["name_key"] for p in professors})
    new_keys = dict(key_pairs)
    for r in reviews:
        r["name_key"] = new_keys.get(r["id"], r["name_key"])
    print(f"name keys to set: {len(key_pairs)}")

    rows, coverage = summaries.build_summaries(linked_pages, [r for r in reviews if r["visible"]],
                                               page_slug, name_key_slug, set(slug_by_id.values()))
    _print("coverage", coverage)
    rows += blend(rows)

    catalog = read_models.catalog_rows(professors, links, linked_pages, rows)
    rows = read_models.keep_summaries(rows, {r["slug"] for r in catalog})
    courses = read_models.course_rows(catalog_courses, rows)
    counts = read_models.stats(catalog, courses, rows)
    _print("read models", {**counts, "summary_rows": len(rows)})
    missing_key = sum(1 for r in reviews if r["name_key"] is None)
    print(f"rmp_reviews left with no name_key (invisible on professor pages): {missing_key}")

    errors = read_models.verify(catalog, courses)
    if errors:
        for e in errors:
            print(f"VERIFY FAILED: {e}")
        return 1
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    # Every write waits for verify, so a failed run leaves no rows behind.
    roster.apply_roster(conn, new_links, new_professors)
    print(f"course codes changed: {course_codes.apply_codes(conn, pairs)}")
    print(f"name keys changed: {name_keys.apply_name_keys(conn, key_pairs)}")
    read_models.write(conn, catalog, courses, rows, counts)
    print("swapped in professors_catalog, course_catalog, source_summary; data_version bumped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
