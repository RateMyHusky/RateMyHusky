"""Rebuild everything the site reads, from the database alone (spec §5.3).

    python -m pipeline.run --dry-run   # compute + verify, write nothing
    python -m pipeline.run             # write (back up first: python backup_db.py)

stdout carries counts only.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone

import moderation

from . import banner_roster, course_codes, name_keys, read_models, review_tags, roster, summaries, survey
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
                                 "focus_x, focus_y, origin FROM professors")
    # Before anything reads college: the subject vote and the Law exits skip
    # professors by it.
    recolleged = roster.recollege(professors)
    print(f"colleges from COLLEGE_MAP over the stored label: {dict(sorted(Counter(c for _, c in recolleged).items()))}")
    corrected = dict(recolleged)
    professors = [{**p, "college": corrected.get(p["slug"], p["college"])} for p in professors]

    catalog_courses = fetch_all(conn, "SELECT code, name, department, subject, search_text, is_placeholder "
                                      "FROM catalog_courses")
    catalog_courses += survey.approved_courses(
        fetch_all(conn, "SELECT code, name FROM survey_pending_courses WHERE status = 'approved'"),
        catalog_courses)

    new_links, new_professors, counts = roster.resolve_roster(pages, links, professors)
    _print("roster", counts)
    links, professors = links + new_links, professors + new_professors
    bci = fetch_all(conn, "SELECT subject_course, instructor_key, instructor_name, professor_slug, "
                          "match_method, terms_taught, sections, last_term_code "
                          "FROM banner_course_instructors")
    # Banner-only professors' departments are earlier guesses, so they don't vote.
    departments = banner_roster.subject_departments(
        bci, {p["slug"]: p["department"] for p in professors if p.get("origin") != "banner"})
    new_banner, banner_counts = banner_roster.resolve_banner_professors(bci, professors, departments)
    _print("banner roster", banner_counts)
    professors = professors + new_banner
    track_sql_rows = fetch_all(conn, banner_roster.TRACK_SECTIONS_SQL)
    track_rows, cps_voted = banner_roster.split_cps_vote(track_sql_rows)
    near_bar = sorted(banner_roster.cps_vote_near_bar(track_sql_rows).items(), key=lambda kv: kv[1])
    near_bar = f" (near the bar: {', '.join(f'{s} {share:.0%}' for s, share in near_bar)})" if near_bar else ""
    print(f"CPS Quarter subjects by vote: {len(cps_voted)}{near_bar}; "
          f"not in the catalog's CPS list: {' '.join(sorted(cps_voted - banner_roster.CPS_SUBJECTS)) or 'none'}")
    # New Banner professors are linked in the database only at apply time, so
    # their keys come from the rows just resolved.
    new_slug_by_key = {p["name_key"]: p["slug"] for p in new_banner}
    colleges = banner_roster.track_colleges(track_rows, new_slug_by_key)
    print(f"colleges from term track: {dict(sorted(Counter(colleges.values()).items()))}")
    exits = banner_roster.track_exits(track_rows, new_slug_by_key, professors, bci,
                                      banner_roster.subject_colleges(bci, professors,
                                                                     banner_roster.CPS_SUBJECTS | cps_voted))
    exits = {slug: c for slug, c in exits.items() if slug not in colleges}
    print(f"out of Law by term track: {dict(sorted(Counter(exits.values()).items()))}")
    colleges = {**exits, **colleges}
    # Alias-aware, so a page created before its professor's denial request still drops.
    professors, links = read_models.drop_denied(professors, links, banner_roster.is_denied_banner_key)

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
    ratings = fetch_all(conn, "SELECT id::text AS id, professor_slug, course_code, rating, difficulty, hours, "
                              "grade, comment, hold_reasons, updated_at "
                              "FROM survey_ratings WHERE status = 'accepted' AND professor_slug IS NOT NULL")
    now = datetime.now(timezone.utc)
    checked = fetch_all(conn, f"SELECT value FROM stats_cache WHERE key = '{survey.SURGE_CHECKED_KEY}'")
    surge = survey.surge_ids(ratings, now, datetime.fromtimestamp(checked[0]["value"], timezone.utc)
                             if checked else None)
    if surge:
        print(f"::warning::{len(surge)} survey ratings in a weekly surge are left out and held for review "
              "(python review_ratings.py list)")
    ratings = [r for r in ratings if r["id"] not in surge]
    survey_summary = survey.survey_rows(ratings)
    print(f"survey: ratings={len(ratings)}, surge={len(surge)}, rows={len(survey_summary)}")
    rows += survey_summary
    rows += blend(rows)

    catalog = read_models.catalog_rows(professors, links, linked_pages, rows, colleges=colleges)
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
    banner_roster.apply_banner_professors(conn, new_banner)
    print(f"course codes changed: {course_codes.apply_codes(conn, pairs)}")
    print(f"name keys changed: {name_keys.apply_name_keys(conn, key_pairs)}")
    review_tags.rebuild_if_present(conn)  # tags follow name_key remaps, pruned reviews, moderation
    print(f"survey ratings held as a weekly surge: {survey.apply_surge_holds(conn, surge)}")
    read_models.write(conn, catalog, courses, rows, counts)
    print("replaced professors_catalog, course_catalog, source_summary; data_version bumped")
    survey.mark_surge_checked(conn, now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
