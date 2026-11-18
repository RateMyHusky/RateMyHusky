"""Match RMP pages to professors (spec §5.3.1).

A page already in rmp_links keeps its frozen slug. A new page links to the
professor whose name_key its name resolves to, else to the one professor its
name is a nickname of (pipeline.duplicates), else becomes a new professor.
Existing slugs and names are never changed.
"""

from collections import Counter, defaultdict

from denylist import is_denied_key
from prof_aliases import NOT_DUPLICATES, rmp_link_key

from .db import chunk_insert
from .duplicates import NicknameIndex, survivor
from .names import get_college, name_to_slug, tidy_name
from .rmp_fields import rmp_id
from .seed import LINK_FIELDS, PROFESSOR_FIELDS


def unique_slug(base, taken):
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def resolve_roster(pages, links, professors, is_denied=is_denied_key, hidden=()):
    """(new link rows, new professor rows, counts). Pure; inputs are not modified.

    `hidden` is the slugs merged away (merged_slugs), never a nickname target.
    counts["created"] is the new professors that will be listed; one whose page
    went to an existing professor by nickname is counted in "nickname" instead.
    """
    known = {l["rmp_id"] for l in links}
    slug_by_key = {p["name_key"]: p["slug"] for p in professors}
    taken = {p["slug"] for p in professors}
    new_links, new_professors = [], []
    nicknames = NicknameIndex([p for p in professors if p["slug"] not in hidden])
    counts = dict.fromkeys(("known", "exact", "created", "nickname", "no_rmp_id", "denied"), 0)
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
            created = {"slug": slug, "name": tidy_name(page["name"]), "name_key": key,
                       "department": page["department"], "college": get_college(page["department"]),
                       "image_url": None, "focus_x": None, "focus_y": None}
            new_professors.append(created)
            nicknames.add(created)
            slug_by_key[key] = slug
            taken.add(slug)
        else:
            counts["exact"] += 1
        known.add(pid)
        new_links.append({"rmp_id": pid, "rmp_name": page["name"], "rmp_department": page["department"],
                          "professor_url": page["professor_url"], "slug": slug, "match_method": "exact"})
    # Decided once every new professor is indexed, so "Tom X" and "Thomas X"
    # arriving in one run still end up one profile. A professor whose page goes
    # elsewhere is still created, so its name_key isn't created again and
    # NOT_DUPLICATES can send the page back to it; it just never shows.
    by_slug = {p["slug"]: p for p in new_professors}
    for l in new_links:
        created = by_slug.get(l["slug"])
        if created is None:
            continue
        existing = nicknames.target(created["name_key"], created["department"], created["slug"])
        if existing and survivor(created, existing)[0] is existing:
            l["slug"] = existing["slug"]
    linked = {l["slug"] for l in new_links}
    counts["created"] = sum(1 for p in new_professors if p["slug"] in linked)
    counts["nickname"] = len(new_professors) - counts["created"]
    return new_links, new_professors, counts


def recollege(professors):
    """[(slug, college)] for professors whose stored college is no longer
    get_college's for their department: a label corrected after they were
    created. A department COLLEGE_MAP doesn't list is left alone rather than
    sent to Other, so a key removed or renamed in COLLEGE_MAP leaves its
    professors on their old college. Pure. run.py applies these to the
    professors it loads and never writes them back: only the pipeline reads
    professors.college, so the catalog and every vote see the correction, and
    the next edit to an existing key is picked up the same way."""
    looked_up = ((p, get_college(p["department"], None)) for p in professors)
    return [(p["slug"], college) for p, college in looked_up
            if college is not None and college != p["college"]]


def _slugs_by_key(professors):
    out = defaultdict(list)
    for p in professors:
        out[p["name_key"]].append(p["slug"])
    return out


def plan_relinks(pages, links, professors):
    """({rmp_id: (old slug, new slug)}, skip counts) for linked pages a reviewer
    has pointed at a different professor. Pure.

    Links are frozen so a page keeps its professor when RMP renames it. Only an
    RMP_MANUAL_LINKS entry, a reviewer's decision about that exact RMP name,
    moves one. An ALIAS_MAP spelling never does: a generic one like "matt lee"
    could take a different person's page. A link stored as 'manual' was already
    settled by a reviewer and is never moved again, and a target name_key that
    more than one professor holds is ambiguous, so it is skipped too.
    """
    link_by_id = {l["rmp_id"]: l for l in links}
    slugs_by_key = _slugs_by_key(professors)
    moves, skipped = {}, Counter()
    for page in pages:
        link = link_by_id.get(rmp_id(page["professor_url"]))
        if link is None:
            continue
        key, method = rmp_link_key(page["name"])
        targets = slugs_by_key.get(key, [])
        if method != "manual" or link["slug"] in targets:
            continue
        if link["match_method"] == "manual":
            skipped["manual_in_db"] += 1
        elif len(targets) != 1:
            skipped["ambiguous" if targets else "no_target"] += 1
        else:
            moves[link["rmp_id"]] = (link["slug"], targets[0])
    return moves, dict(skipped)


def plan_nickname_relinks(pages, links, professors, nickname):
    """(moves, reverts), each {rmp_id: (old slug, new slug)}, for the nickname
    merges pipeline.duplicates found. Pure.

    `nickname` is {merged-away slug: surviving slug}. Every page of a merged-away
    professor moves to the survivor. A pair later put in NOT_DUPLICATES is no
    longer in `nickname`, and each of its pages moves back to the professor its
    own name resolves to (a revert). Only pages move back: the bookmarks, survey
    ratings, Banner rows and photo the merge moved can't be told apart from the
    survivor's own, so run.py warns and a person moves them. A page an RMP_MANUAL_LINKS entry or a
    reviewer ('manual' in the database) settled is never touched. Unlike a
    manual move, these keep their stored match_method, since the decision is
    recomputed from the data every run.
    """
    link_by_id = {l["rmp_id"]: l for l in links}
    slugs_by_key = _slugs_by_key(professors)
    key_by_slug = {p["slug"]: p["name_key"] for p in professors}
    moves, reverts = {}, {}
    for page in pages:
        link = link_by_id.get(rmp_id(page["professor_url"]))
        if link is None or link["match_method"] == "manual":
            continue
        key, method = rmp_link_key(page["name"])
        if method == "manual":
            continue
        if link["slug"] in nickname:
            moves[link["rmp_id"]] = (link["slug"], nickname[link["slug"]])
            continue
        homes = slugs_by_key.get(key, [])
        if len(homes) == 1 and homes[0] != link["slug"] \
                and frozenset((key, key_by_slug.get(link["slug"]))) in NOT_DUPLICATES:
            reverts[link["rmp_id"]] = (link["slug"], homes[0])
    return moves, reverts


def relink(links, moves, method="manual"):
    """`links` with each moved page pointing at its new professor, stored as
    `method` (None keeps the stored one). Pure."""
    return [{**l, "slug": moves[l["rmp_id"]][1], "match_method": method or l["match_method"]}
            if l["rmp_id"] in moves else l for l in links]


def merged_slugs(professors, links_after, moves, nickname=None):
    """{old slug: slug it merged into} for every RMP professor an RMP_MANUAL_LINKS
    entry or a nickname merge (`nickname`, from pipeline.duplicates) left with no
    page: this run's moves and every earlier one. Pure.

    Recomputed each run, so a row that points at the old slug later (a Banner
    match, a survey rating) still follows the merge. The old professor stays in
    `professors`, so its name_key isn't created again; it just never shows.
    A merge stays known as long as the pages under the old professor's own name
    sit on one other professor, even once the rule that made it no longer
    finds the pair. Chains (a -> b -> c) resolve to their end.
    """
    linked = {l["slug"] for l in links_after}
    slugs_by_key = _slugs_by_key(professors)
    key_by_slug = {p["slug"]: p["name_key"] for p in professors}
    nickname = nickname or {}
    pages_now = defaultdict(set)        # name_key a page was filed under -> where it sits
    for l in links_after:
        key, method = rmp_link_key(l.get("rmp_name") or "")
        if method != "manual":
            pages_now[key].add(l["slug"])
    merged = {old: new for old, new in moves.values() if old not in linked}
    for p in professors:
        if p.get("origin", "rmp") != "rmp" or p["slug"] in linked or p["slug"] in merged:
            continue
        if p["slug"] in nickname:
            merged[p["slug"]] = nickname[p["slug"]]
            continue
        key, method = rmp_link_key(p["name_key"])
        targets = slugs_by_key.get(key, [])
        if method == "manual" and len(targets) == 1 and targets[0] != p["slug"]:
            merged[p["slug"]] = targets[0]
            continue
        [*where] = pages_now.get(p["name_key"], ())
        if len(where) == 1 and frozenset((p["name_key"], key_by_slug.get(where[0]))) not in NOT_DUPLICATES:
            merged[p["slug"]] = where[0]

    def end(slug, seen):
        while slug in merged and slug not in seen:
            seen.add(slug)
            slug = merged[slug]
        return slug
    resolved = {old: end(new, {old}) for old, new in merged.items()}
    return {old: new for old, new in resolved.items() if new != old}


def remap_slugs(rows, merged, field="professor_slug"):
    """`rows` with any merged-away slug in `field` replaced by its survivor. Pure."""
    return [{**r, field: merged[r[field]]} if r.get(field) in merged else r for r in rows]


PHOTO_FIELDS = ("image_url", "focus_x", "focus_y")


def carry_photos(professors, merged):
    """(professors, {survivor slug: photo fields}): a merged-away professor's
    photo copied onto its survivor when the survivor has none. Pure. Without
    this a merge drops the photo, since the old professor leaves the catalog.
    The second value is what apply_merges writes, so the rule lives only here."""
    by_slug = {p["slug"]: p for p in professors}
    photo = {}
    for old, new in merged.items():
        if old in by_slug and new in by_slug and new not in photo \
                and by_slug[old]["image_url"] and not by_slug[new]["image_url"]:
            photo[new] = {f: by_slug[old][f] for f in PHOTO_FIELDS}
    return [{**p, **photo[p["slug"]]} if p["slug"] in photo else p for p in professors], photo


# Every table that names a professor by slug, with the other columns of its
# unique key: a row the survivor already has under that key wins, and the
# merged-away copy is dropped so the move can't break the index. survey_ratings
# is handled on its own (a device keeps its newer rating). ask_log is a log of
# past questions and stays as written.
SLUG_TABLES = (
    ("banner_course_instructors", "professor_slug", None),
    ("professor_teaching", "professor_slug", None),
    ("reddit_mentions", "professor_slug", None),
    ("reddit_sentiment", "professor_slug", ("source_type", "source_id")),
    ("evidence", "professor_slug", ("source", "source_ref", "course_code")),
    ("professor_aliases", "slug", ("alias_key",)),
    ("bookmarks", "item_key", ("user_sub", "item_type")),
)
SURVEY_KEY = ("pending_professor_id", "course_code", "pending_course_id")


def apply_merges(conn, moves, merged, photos, kept_method=None):
    """Write the moves (as 'manual'), the `kept_method` moves (nickname merges
    and reverts, keeping their stored match_method), the carried photos, and
    every row that still names a merged-away slug. Does not commit: run.py calls it just before
    read_models.write, so it lands in the same transaction as the catalog that
    stops listing the old slug. Idempotent, so a run with nothing left to move
    changes nothing."""
    cur = conn.cursor()
    for pid, (old, new) in moves.items():
        cur.execute("UPDATE rmp_links SET slug = %s, match_method = 'manual' WHERE rmp_id = %s AND slug = %s",
                    (new, pid, old))
    for pid, (old, new) in (kept_method or {}).items():
        cur.execute("UPDATE rmp_links SET slug = %s WHERE rmp_id = %s AND slug = %s", (new, pid, old))
    for slug, p in photos.items():
        cur.execute("UPDATE professors SET image_url = %s, focus_x = %s, focus_y = %s WHERE slug = %s",
                    (p["image_url"], p["focus_x"], p["focus_y"], slug))
    for old, new in merged.items():
        same = " AND ".join(f"d.{c} IS NOT DISTINCT FROM o.{c}" for c in ("device_hash",) + SURVEY_KEY)
        cur.execute(f"""
            DELETE FROM survey_ratings d USING survey_ratings o
            WHERE d.id <> o.id AND {same}
              AND ((d.professor_slug = %s AND o.professor_slug = %s)
                OR (d.professor_slug = %s AND o.professor_slug = %s))
              AND (d.updated_at, d.id) < (o.updated_at, o.id)""", (old, new, new, old))
        cur.execute("UPDATE survey_ratings SET professor_slug = %s WHERE professor_slug = %s", (new, old))
        for table, col, key in SLUG_TABLES:
            if key:
                same = " AND ".join(f"d.{c} IS NOT DISTINCT FROM o.{c}" for c in key)
                extra = " AND d.item_type = 'professor'" if table == "bookmarks" else ""
                cur.execute(f"DELETE FROM {table} d USING {table} o "
                            f"WHERE d.{col} = %s AND o.{col} = %s AND {same}{extra}", (old, new))
            where = f"{col} = %s" + (" AND item_type = 'professor'" if table == "bookmarks" else "")
            cur.execute(f"UPDATE {table} SET {col} = %s WHERE {where}", (new, old))


def apply_roster(conn, new_links, new_professors):
    cur = conn.cursor()
    chunk_insert(cur, f"INSERT INTO professors ({', '.join(PROFESSOR_FIELDS)}) VALUES %s "
                      "ON CONFLICT (slug) DO NOTHING",
                 [tuple(p[f] for f in PROFESSOR_FIELDS) for p in new_professors])
    chunk_insert(cur, f"INSERT INTO rmp_links ({', '.join(LINK_FIELDS)}) VALUES %s "
                      "ON CONFLICT (rmp_id) DO NOTHING",
                 [tuple(l[f] for f in LINK_FIELDS) for l in new_links])
    conn.commit()
