"""Rebuild professors_catalog, course_catalog and source_summary (spec §5.3.5-6).

All three are replaced in one transaction (DELETE + INSERT), together with the
homepage counts in stats_cache and data_version += 1, which invalidates the
API's caches. Readers keep the previous snapshot until COMMIT.
"""

import re

from psycopg2.extras import Json

from denylist import is_denied_key
from teaching_history import COURSE_SUCCESSORS

from .db import chunk_insert

MIN_PROFESSORS = 3000
MIN_COURSES = 5000

CATALOG_COLUMNS = ("slug", "name", "name_key", "department", "college", "avg_rating", "rmp_rating",
                   "num_ratings", "total_reviews", "would_take_again_pct", "difficulty",
                   "professor_url", "image_url", "focus_x", "focus_y", "total_comments")
COURSE_COLUMNS = ("code", "name", "department", "subject", "search_text",
                  "avg_rating", "difficulty", "num_ratings")
SUMMARY_COLUMNS = ("professor_slug", "course_code", "source", "rating", "difficulty",
                   "would_take_again_pct", "num_ratings", "num_comments", "hours_per_week",
                   "rating_distribution", "grade_distribution")

READ_MODELS = ("professors_catalog", "course_catalog", "source_summary")

STATS_SQL = (
    "INSERT INTO stats_cache (key, value) VALUES "
    "('professors', %s), ('courses', %s), ('comments', %s), ('departments', %s) "
    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value")

DATA_VERSION_SQL = (
    "INSERT INTO stats_cache (key, value) "
    "SELECT 'data_version', COALESCE(max(value), 0) + 1 FROM stats_cache "
    "WHERE key = 'data_version' "
    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value")


def _index(summary_rows, source):
    return {(r["professor_slug"], r["course_code"]): r for r in summary_rows if r["source"] == source}


def drop_denied(professors, links, is_denied=is_denied_key):
    kept = [p for p in professors if not is_denied(p["name_key"])]
    slugs = {p["slug"] for p in kept}
    return kept, [l for l in links if l["slug"] in slugs]


def catalog_rows(professors, links, pages, summary_rows, is_denied=is_denied_key, colleges=None):
    """colleges overrides professors.college per slug. professors.college is set
    once from a department label and never rewritten, so a better source is
    applied here, where the catalog is rebuilt every run."""
    colleges = colleges or {}
    ratings_by_page = {p["rmp_id"]: p["num_ratings"] or 0 for p in pages}
    best_url = {}
    for l in sorted(links, key=lambda l: (-ratings_by_page.get(l["rmp_id"], 0), l["rmp_id"])):
        best_url.setdefault(l["slug"], l["professor_url"])
    blend, rmp = _index(summary_rows, "blend"), _index(summary_rows, "rmp")
    rows = []
    for p in professors:
        # An RMP professor needs a link; a Banner or survey one is listed without.
        if (p.get("origin", "rmp") == "rmp" and p["slug"] not in best_url) or is_denied(p["name_key"]):
            continue
        b = blend.get((p["slug"], ""), {})
        r = rmp.get((p["slug"], ""), {})
        rows.append({
            "slug": p["slug"], "name": p["name"], "name_key": p["name_key"],
            "department": p["department"], "college": colleges.get(p["slug"], p["college"]),
            "avg_rating": b.get("rating"), "rmp_rating": r.get("rating"),
            "num_ratings": r.get("num_ratings", 0), "total_reviews": b.get("num_ratings", 0),
            "would_take_again_pct": b.get("would_take_again_pct"), "difficulty": b.get("difficulty"),
            "professor_url": best_url.get(p["slug"]), "image_url": p["image_url"],
            "focus_x": p["focus_x"], "focus_y": p["focus_y"],
            "total_comments": b.get("num_comments", 0),
        })
    return rows


def course_search_text(code, search_text):
    """search_text with the code's spaced form added ("cs3500 ..." also holds "cs 3500"), so a
    search typed with a space matches at every prefix ("cs 3", "cs 35"), not only once the
    API joins a complete code."""
    text = (search_text or "").lower()
    m = re.fullmatch(r"([a-z]+)(\d+)", (code or "").lower())
    spaced = f"{m.group(1)} {m.group(2)}" if m else ""
    return f"{text} {spaced}".strip() if spaced and spaced not in text else text


def course_rows(catalog_courses, summary_rows):
    blend = _index(summary_rows, "blend")
    rows = []
    for c in catalog_courses:
        b = blend.get(("", c["code"]), {})
        if c.get("is_placeholder") and not b:
            continue
        rows.append({"code": c["code"], "name": c["name"], "department": c["department"],
                     "subject": c["subject"], "search_text": course_search_text(c["code"], c["search_text"]),
                     "avg_rating": b.get("rating"), "difficulty": b.get("difficulty"),
                     "num_ratings": b.get("num_ratings", 0)})
    return rows


def retired_courses(catalog_courses, titles):
    """catalog_courses-shaped rows for the codes COURSE_SUCCESSORS retires once the current
    catalog edition stops listing them (CS2500 after the Fall 2025 intro redesign). Their
    reviews stay on the old code, so without a row they get no course code, no course page
    and no search result. The department and subject are the successor's; `titles` maps a
    code to Banner's title for it, and a code Banner never titled is skipped. Pure."""
    by_code = {c["code"]: c for c in catalog_courses}
    out = []
    for old, (new, _) in COURSE_SUCCESSORS.items():
        successor = by_code.get(new)
        if old in by_code or not successor or not titles.get(old):
            continue
        # Banner titles can carry doubled spaces; collapse them so name matches search_text.
        name = " ".join(titles[old].split())
        out.append({"code": old, "name": name, "department": successor["department"],
                    "subject": successor["subject"],
                    "search_text": f"{old} {name}".lower(),
                    "is_placeholder": False})
    return out


def keep_summaries(summary_rows, catalog_slugs):
    return [r for r in summary_rows if r["professor_slug"] == "" or r["professor_slug"] in catalog_slugs]


def _shown(catalog):
    """Rows with an RMP link or ratings: what the homepage counts and verify floors on."""
    return [r for r in catalog if r["professor_url"] or r["num_ratings"] > 0]


def stats(catalog, courses, summary_rows):
    shown = _shown(catalog)
    return {"professors": len(shown), "courses": len(courses),
            "comments": sum(r["total_comments"] for r in catalog),
            "departments": len({r["department"] for r in shown if r["department"]})}


def verify(catalog, courses):
    errors = []
    shown = len(_shown(catalog))
    if shown < MIN_PROFESSORS:
        errors.append(f"professors {shown} < {MIN_PROFESSORS}")
    if len(courses) < MIN_COURSES:
        errors.append(f"courses {len(courses)} < {MIN_COURSES}")
    return errors


def _insert(cur, table, columns, rows, json_columns=()):
    values = [tuple(Json(r[c]) if c in json_columns else r[c] for c in columns) for r in rows]
    chunk_insert(cur, f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s", values)


def write(conn, catalog, courses, summary_rows, counts):
    """Replace the read models and bump data_version, committing once.

    Any failure rolls the whole thing back, so the site keeps serving the last
    good data. No DDL: the tables keep db/postgres/'s schema exactly.
    """
    try:
        with conn.cursor() as cur:
            for table, columns, rows, json_cols in (
                ("professors_catalog", CATALOG_COLUMNS, catalog, ()),
                ("course_catalog", COURSE_COLUMNS, courses, ()),
                ("source_summary", SUMMARY_COLUMNS, summary_rows,
                 ("rating_distribution", "grade_distribution")),
            ):
                cur.execute(f"DELETE FROM {table}")
                _insert(cur, table, columns, rows, json_cols)
            cur.execute(STATS_SQL, (counts["professors"], counts["courses"],
                                    counts["comments"], counts["departments"]))
            cur.execute(DATA_VERSION_SQL)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
