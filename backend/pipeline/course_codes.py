"""Fill rmp_reviews.course_code (spec §5.3.2).

Recomputed for every row on every run, so a newly loaded catalog resolves codes
that were NULL before. One batched UPDATE through a temp table.
"""

import re

from .db import chunk_insert

_CODE = re.compile(r"^[A-Z]{2,5}\d{4}")


def normalize_code(raw, valid):
    """"cs 2500" -> "CS2500" when the catalog has it, else None."""
    s = re.sub(r"[^A-Za-z0-9]", "", str(raw or "")).upper()
    m = _CODE.match(s)
    return m.group(0) if m and m.group(0) in valid else None


def plan_codes(reviews, valid):
    return [(r["id"], normalize_code(r["course"], valid)) for r in reviews]


def apply_codes(conn, pairs):
    cur = conn.cursor()
    cur.execute("SET experimental_enable_temp_tables = 'on'")
    cur.execute("CREATE TEMP TABLE _course_code_map (id INT8 PRIMARY KEY, course_code TEXT)")
    chunk_insert(cur, "INSERT INTO _course_code_map (id, course_code) VALUES %s", pairs)
    cur.execute("""
        UPDATE rmp_reviews r SET course_code = m.course_code
        FROM _course_code_map m
        WHERE r.id = m.id AND r.course_code IS DISTINCT FROM m.course_code
    """)
    changed = cur.rowcount
    cur.execute("DROP TABLE _course_code_map")
    conn.commit()
    return changed
