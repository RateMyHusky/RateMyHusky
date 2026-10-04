"""Fill rmp_reviews.name_key.

Professor pages and course pages find a professor's reviews by name_key, and a
freshly loaded review has none. A review on a linked RMP page takes the key of
the professor that page links to. A review on no linked page, with no key yet,
takes its own name's key, as precompute's backfill did. One batched UPDATE
through a temp table.
"""

from prof_aliases import rmp_link_key

from .db import chunk_insert


def plan_name_keys(reviews, page_slug, key_by_slug):
    """(id, name_key) for every review whose stored key differs from its page's
    professor, plus every unkeyed review on no linked page."""
    pairs = []
    for r in reviews:
        slug = page_slug.get((r["professor_name"], r["department"]))
        if slug and r["name_key"] != key_by_slug[slug]:
            pairs.append((r["id"], key_by_slug[slug]))
        elif not slug and r["name_key"] is None and r["professor_name"]:
            pairs.append((r["id"], rmp_link_key(r["professor_name"])[0]))
    return pairs


def apply_name_keys(conn, pairs):
    cur = conn.cursor()
    cur.execute("SET experimental_enable_temp_tables = 'on'")
    cur.execute("CREATE TEMP TABLE _name_key_map (id INT8 PRIMARY KEY, name_key TEXT)")
    chunk_insert(cur, "INSERT INTO _name_key_map (id, name_key) VALUES %s", pairs)
    cur.execute("""
        UPDATE rmp_reviews r SET name_key = m.name_key
        FROM _name_key_map m
        WHERE r.id = m.id
    """)
    changed = cur.rowcount
    cur.execute("DROP TABLE _name_key_map")
    conn.commit()
    return changed
