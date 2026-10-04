"""Match RMP pages to professors (spec §5.3.1).

A page already in rmp_links keeps its frozen slug. A new page links to the
professor whose name_key its name resolves to, else becomes a new professor.
Existing slugs and names are never changed.
"""

from denylist import is_denied_key
from prof_aliases import rmp_link_key

from .db import chunk_insert
from .names import get_college, name_to_slug
from .rmp_fields import rmp_id
from .seed import LINK_FIELDS, PROFESSOR_FIELDS


def unique_slug(base, taken):
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def resolve_roster(pages, links, professors, is_denied=is_denied_key):
    """(new link rows, new professor rows, counts). Pure; inputs are not modified."""
    known = {l["rmp_id"] for l in links}
    slug_by_key = {p["name_key"]: p["slug"] for p in professors}
    taken = {p["slug"] for p in professors}
    new_links, new_professors = [], []
    counts = dict.fromkeys(("known", "exact", "created", "no_rmp_id", "denied"), 0)
    denied_ids = {rmp_id(p["professor_url"]) for p in pages if is_denied(rmp_link_key(p["name"])[0])} - {None}
    for page in pages:
        pid = rmp_id(page["professor_url"])
        if pid is None:
            counts["no_rmp_id"] += 1
            continue
        key, _ = rmp_link_key(page["name"])
        if pid in denied_ids:
            counts["denied"] += 1
            continue
        if pid in known:
            counts["known"] += 1
            continue
        slug = slug_by_key.get(key)
        if slug is None:
            slug = unique_slug(name_to_slug(key), taken)
            new_professors.append({"slug": slug, "name": page["name"], "name_key": key,
                                   "department": page["department"],
                                   "college": get_college(page["department"]),
                                   "image_url": None, "focus_x": None, "focus_y": None})
            slug_by_key[key] = slug
            taken.add(slug)
            counts["created"] += 1
        else:
            counts["exact"] += 1
        known.add(pid)
        new_links.append({"rmp_id": pid, "rmp_name": page["name"], "rmp_department": page["department"],
                          "professor_url": page["professor_url"], "slug": slug, "match_method": "exact"})
    return new_links, new_professors, counts


def apply_roster(conn, new_links, new_professors):
    cur = conn.cursor()
    chunk_insert(cur, f"INSERT INTO professors ({', '.join(PROFESSOR_FIELDS)}) VALUES %s "
                      "ON CONFLICT (slug) DO NOTHING",
                 [tuple(p[f] for f in PROFESSOR_FIELDS) for p in new_professors])
    chunk_insert(cur, f"INSERT INTO rmp_links ({', '.join(LINK_FIELDS)}) VALUES %s "
                      "ON CONFLICT (rmp_id) DO NOTHING",
                 [tuple(l[f] for f in LINK_FIELDS) for l in new_links])
    conn.commit()
