"""Rebuild professors_catalog, course_catalog and source_summary (spec §5.3.5-6).

Build into *_new tables, verify, then swap each in. stats_cache gets the
homepage counts and data_version += 1, which invalidates the API's caches.
"""

from psycopg2.extras import Json

from denylist import is_denied_key

from .db import chunk_insert, swap_in
from .schema import SOURCE_SUMMARY_DDL

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

PROFESSORS_CATALOG_DDL = """
CREATE TABLE professors_catalog_new (
  slug TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL,
  department TEXT, college TEXT, avg_rating FLOAT, rmp_rating FLOAT,
  num_ratings INT DEFAULT 0, total_reviews INT DEFAULT 0, would_take_again_pct FLOAT,
  difficulty FLOAT, professor_url TEXT, image_url TEXT, focus_x FLOAT, focus_y FLOAT,
  total_comments INT DEFAULT 0,
  INDEX idx_pc_name_key (name_key), INDEX idx_pc_college (college), INDEX idx_pc_dept (department)
)"""

COURSE_CATALOG_DDL = """
CREATE TABLE course_catalog_new (
  code TEXT PRIMARY KEY, name TEXT, department TEXT, subject TEXT, search_text TEXT,
  avg_rating FLOAT, difficulty FLOAT, num_ratings INT DEFAULT 0,
  INDEX idx_cc_dept (department)
)"""


def _index(summary_rows, source):
    return {(r["professor_slug"], r["course_code"]): r for r in summary_rows if r["source"] == source}


def drop_denied(professors, links, is_denied=is_denied_key):
    kept = [p for p in professors if not is_denied(p["name_key"])]
    slugs = {p["slug"] for p in kept}
    return kept, [l for l in links if l["slug"] in slugs]


def catalog_rows(professors, links, pages, summary_rows, is_denied=is_denied_key):
    ratings_by_page = {p["rmp_id"]: p["num_ratings"] or 0 for p in pages}
    best_url = {}
    for l in sorted(links, key=lambda l: (-ratings_by_page.get(l["rmp_id"], 0), l["rmp_id"])):
        best_url.setdefault(l["slug"], l["professor_url"])
    blend, rmp = _index(summary_rows, "blend"), _index(summary_rows, "rmp")
    rows = []
    for p in professors:
        if p["slug"] not in best_url or is_denied(p["name_key"]):
            continue
        b = blend.get((p["slug"], ""), {})
        r = rmp.get((p["slug"], ""), {})
        rows.append({
            "slug": p["slug"], "name": p["name"], "name_key": p["name_key"],
            "department": p["department"], "college": p["college"],
            "avg_rating": b.get("rating"), "rmp_rating": r.get("rating"),
            "num_ratings": r.get("num_ratings", 0), "total_reviews": b.get("num_ratings", 0),
            "would_take_again_pct": b.get("would_take_again_pct"), "difficulty": b.get("difficulty"),
            "professor_url": best_url[p["slug"]], "image_url": p["image_url"],
            "focus_x": p["focus_x"], "focus_y": p["focus_y"],
            "total_comments": b.get("num_comments", 0),
        })
    return rows


def course_rows(catalog_courses, summary_rows):
    blend = _index(summary_rows, "blend")
    rows = []
    for c in catalog_courses:
        b = blend.get(("", c["code"]), {})
        if c.get("is_placeholder") and not b:
            continue
        rows.append({"code": c["code"], "name": c["name"], "department": c["department"],
                     "subject": c["subject"], "search_text": (c["search_text"] or "").lower(),
                     "avg_rating": b.get("rating"), "difficulty": b.get("difficulty"),
                     "num_ratings": b.get("num_ratings", 0)})
    return rows


def keep_summaries(summary_rows, catalog_slugs):
    return [r for r in summary_rows if r["professor_slug"] == "" or r["professor_slug"] in catalog_slugs]


def stats(catalog, courses, summary_rows):
    return {"professors": len(catalog), "courses": len(courses),
            "comments": sum(r["total_comments"] for r in catalog),
            "departments": len({r["department"] for r in catalog if r["department"]})}


def verify(catalog, courses):
    errors = []
    if len(catalog) < MIN_PROFESSORS:
        errors.append(f"professors {len(catalog)} < {MIN_PROFESSORS}")
    if len(courses) < MIN_COURSES:
        errors.append(f"courses {len(courses)} < {MIN_COURSES}")
    return errors


def _insert(cur, table, columns, rows, json_columns=()):
    values = [tuple(Json(r[c]) if c in json_columns else r[c] for c in columns) for r in rows]
    chunk_insert(cur, f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s", values)


def write(conn, catalog, courses, summary_rows, counts):
    cur = conn.cursor()
    for table, ddl, columns, rows, json_cols in (
        ("professors_catalog", PROFESSORS_CATALOG_DDL, CATALOG_COLUMNS, catalog, ()),
        ("course_catalog", COURSE_CATALOG_DDL, COURSE_COLUMNS, courses, ()),
        ("source_summary", SOURCE_SUMMARY_DDL.format(name="source_summary_new"), SUMMARY_COLUMNS,
         summary_rows, ("rating_distribution", "grade_distribution")),
    ):
        cur.execute(f"DROP TABLE IF EXISTS {table}_new")
        cur.execute(ddl)
        _insert(cur, f"{table}_new", columns, rows, json_cols)
        conn.commit()
    for table in ("professors_catalog", "course_catalog", "source_summary"):
        swap_in(conn, table)
    cur = conn.cursor()
    cur.execute("UPSERT INTO stats_cache VALUES ('professors', %s), ('courses', %s), "
                "('comments', %s), ('departments', %s)",
                (counts["professors"], counts["courses"], counts["comments"], counts["departments"]))
    cur.execute("UPSERT INTO stats_cache (key, value) SELECT 'data_version', COALESCE(max(value), 0) + 1 "
                "FROM stats_cache WHERE key = 'data_version'")
    conn.commit()
