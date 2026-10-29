"""Review held survey ratings and new professors and courses (rating form, plan 3).

    python review_ratings.py list                       # held ratings, pending professors, courses and aliases
    python review_ratings.py approve-rating ID [ID...]  # held -> accepted
    python review_ratings.py reject-rating [--abuse] ID [ID...]  # delete the rating; --abuse also silences its device and IP
    python review_ratings.py remove-comment PUBLIC_ID   # take down a shown comment by the id a report carries
    python review_ratings.py approve-professor ID [--slug SLUG]
    python review_ratings.py merge-professor ID SLUG
    python review_ratings.py reject-professor ID
    python review_ratings.py approve-course ID
    python review_ratings.py merge-course ID CODE
    python review_ratings.py reject-course ID
    python review_ratings.py approve-alias ID           # pending nickname -> searchable
    python review_ratings.py reject-alias ID            # keep the row as rejected so the word isn't suggested again
    python review_ratings.py purge-ip                   # clear IP hashes older than 30 days and expired IP flags

Rating ids may be the short id `list` prints. Each run is one transaction: it
commits at the end, and rolls back and exits 1 on a bad id or a non-pending
entry. Reads ORACLE_DATABASE_URL. `list` prints no hashes or network data.
Approved and merged ratings reach the site on the next pipeline run; a
professor page's student reviews change within minutes, since every command but
list and purge-ip bumps data_version. Approving a rating held as unverified_pair
vouches for that professor teaching that course, so later ratings of the pair
aren't held for it.
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

import ratings
import survey_reviews
from pipeline.read_models import DATA_VERSION_SQL
from pipeline.db import connect
from pipeline.names import get_college, name_to_slug
from pipeline.roster import unique_slug

# `table`: the pending table. `pending`/`final`: the rating columns that hold the
# pending id and the resolved value. `rest`: the other key columns of the
# one-per-device unique index.
PROFESSOR = {"label": "professor", "table": "survey_pending_professors",
             "pending": "pending_professor_id", "final": "professor_slug",
             "resolved": "resolved_slug",
             "rest": ("course_code", "pending_course_id")}
COURSE = {"label": "course", "table": "survey_pending_courses",
          "pending": "pending_course_id", "final": "course_code",
          "resolved": "resolved_code",
          "rest": ("professor_slug", "pending_professor_id")}


class ReviewError(Exception):
    pass


def load_pending(cur, kind, entry_id):
    cur.execute(f"SELECT * FROM {kind['table']} WHERE id = %s FOR UPDATE", (entry_id,))
    row = cur.fetchone()
    if row is None:
        raise ReviewError(f"No {kind['label']} {entry_id}")
    if row["status"] != "pending":
        raise ReviewError(f"{kind['label'].capitalize()} {entry_id} is already {row['status']}")
    return row


def move_ratings(cur, kind, entry_id, value):
    """Point the entry's ratings at `value`; return (moved, held). A device that
    already rated `value` under the same remaining key keeps only its newer rating:
    the loser is deleted first, so the one-per-device index never sees two rows.

    The form skips the pair check while either side is pending, and approving or
    merging an entry is a judgment about it, not about who taught the course. So a
    moved rating on a pair ratings.TAUGHT_SQL doesn't know is held as unverified_pair."""
    a, b = kind["rest"]
    cur.execute(
        f"DELETE FROM survey_ratings d USING survey_ratings o "
        f"WHERE d.id <> o.id AND d.device_hash = o.device_hash "
        f"AND d.{a} IS NOT DISTINCT FROM o.{a} AND d.{b} IS NOT DISTINCT FROM o.{b} "
        f"AND ((d.{kind['pending']} = %s AND o.{kind['final']} = %s) "
        f"OR (d.{kind['final']} = %s AND o.{kind['pending']} = %s)) "
        f"AND (d.updated_at, d.id) < (o.updated_at, o.id)",
        (entry_id, value, value, entry_id))
    cur.execute(f"UPDATE survey_ratings SET {kind['final']} = %s, {kind['pending']} = NULL "
                f"WHERE {kind['pending']} = %s RETURNING id::text AS id", (value, entry_id))
    ids = [r["id"] for r in cur.fetchall()]
    taught = ratings.TAUGHT_SQL.format(code="r.course_code", slug="r.professor_slug")
    cur.execute("UPDATE survey_ratings r SET status = 'held', "
                "hold_reasons = concat_ws(',', r.hold_reasons, 'unverified_pair') "
                "WHERE r.id::text = ANY(%s) AND r.professor_slug IS NOT NULL AND r.course_code IS NOT NULL "
                "AND NOT COALESCE(string_to_array(r.hold_reasons, ',') @> ARRAY['unverified_pair'], false) "
                f"AND NOT {taught}", (ids,))
    return len(ids), cur.rowcount


def _moved(moved, held):
    return f"moved {moved} rating(s), held {held} on a pair Banner and RMP never saw (see list)"


def resolve(cur, kind, entry_id, status, value):
    cur.execute(f"UPDATE {kind['table']} SET status = '{status}', {kind['resolved']} = %s "
                f"WHERE id = %s", (value, entry_id))


def reject(cur, kind, entry_id):
    load_pending(cur, kind, entry_id)
    cur.execute(f"DELETE FROM survey_ratings WHERE {kind['pending']} = %s", (entry_id,))
    deleted = cur.rowcount
    cur.execute(f"UPDATE {kind['table']} SET status = 'rejected' WHERE id = %s", (entry_id,))
    return f"Rejected {kind['label']} {entry_id}: deleted {deleted} rating(s)"


def short_id_pattern(rating_id):
    if not re.fullmatch(r"[0-9a-f-]{4,36}", rating_id):
        raise ReviewError(f"Bad rating id {rating_id!r}")
    return rating_id + "%"


def approve_rating(cur, *ids):
    for rating_id in ids:
        cur.execute("UPDATE survey_ratings SET status = 'accepted' "
                    "WHERE id::text LIKE %s AND status = 'held' RETURNING id",
                    (short_id_pattern(rating_id),))
        if len(cur.fetchall()) != 1:
            raise ReviewError(f"{rating_id} is not exactly one held rating")
    return f"Approved {len(ids)} rating(s)"


def flag_abuse(cur, rating_id):
    """Silence the device (for good) and the IP (IP_HASH_DAYS; not on a shared network,
    and not once a purge cleared it) of the one held rating `rating_id`: later ratings
    from either are held as silent_hold. Raises before writing when the id isn't one held rating."""
    cur.execute("SELECT device_hash, ip_hash, network_type FROM survey_ratings "
                "WHERE id::text LIKE %s AND status = 'held' FOR UPDATE", (short_id_pattern(rating_id),))
    found = cur.fetchall()
    if len(found) != 1:
        raise ReviewError(f"{rating_id} is not exactly one held rating")
    row = found[0]
    cur.execute("INSERT INTO rating_flags (kind, value_hash) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING", ("device", row["device_hash"]))
    if row["ip_hash"] and row["network_type"] not in ratings.FLAG_EXEMPT_NETWORKS:
        cur.execute("INSERT INTO rating_flags (kind, value_hash) VALUES (%s, %s) "
                    "ON CONFLICT (kind, value_hash) DO UPDATE SET created_at = now()",
                    ("ip", row["ip_hash"]))


def reject_rating(cur, *ids, abuse=False):
    for rating_id in ids:
        if abuse:
            flag_abuse(cur, rating_id)
        cur.execute("DELETE FROM survey_ratings WHERE id::text LIKE %s AND status = 'held' "
                    "RETURNING id", (short_id_pattern(rating_id),))
        if len(cur.fetchall()) != 1:
            raise ReviewError(f"{rating_id} is not exactly one held rating")
    return f"Rejected {len(ids)} rating(s)"


def remove_comment(cur, review_id):
    """Drop the comment of the review whose public id (the one on the page and in
    a report) is review_id; the rating keeps counting. Needs RATING_SECRET.

    The comment_removed hold reason stays on the row, so an edit that brings a
    comment back is held (server.rate_submit); comment_hash stays too, so the same
    text from another device is held as a duplicate_comment."""
    secret = os.getenv("RATING_SECRET")
    if not secret:
        raise ReviewError("RATING_SECRET is needed to match a public review id")
    cur.execute("SELECT id FROM survey_ratings WHERE comment IS NOT NULL")
    matches = [str(r["id"]) for r in cur.fetchall() if survey_reviews.public_id(secret, r["id"]) == review_id]
    if len(matches) != 1:
        raise ReviewError(f"{review_id} is not exactly one shown review")
    cur.execute("UPDATE survey_ratings SET comment = NULL, hold_reasons = CASE "
                "WHEN hold_reasons IS NULL THEN 'comment_removed' "
                "WHEN ',' || hold_reasons || ',' LIKE '%%,comment_removed,%%' THEN hold_reasons "
                "ELSE hold_reasons || ',comment_removed' END "
                "WHERE id::text = %s RETURNING id", (matches[0],))
    return f"Removed the comment of {matches[0]}"


def approve_professor(cur, entry_id, slug=None):
    row = load_pending(cur, PROFESSOR, entry_id)
    cur.execute("SELECT slug FROM professors WHERE name_key = %s", (row["name_key"],))
    existing = cur.fetchone()
    if existing:
        raise ReviewError(f"{clean(row['name'])} already exists as {existing['slug']}; "
                          f"use merge-professor {entry_id} {existing['slug']}")
    cur.execute("SELECT slug FROM professors ORDER BY slug")
    taken = {r["slug"] for r in cur.fetchall()}
    if slug is None:
        slug = unique_slug(name_to_slug(row["name_key"]), taken)
    elif not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        raise ReviewError(f"Bad slug {slug!r}: use lowercase letters, digits and single hyphens")
    elif slug in taken:
        raise ReviewError(f"Slug {slug} is taken")
    cur.execute("INSERT INTO professors (slug, name, name_key, department, college, origin) "
                "VALUES (%s, %s, %s, %s, %s, 'survey')",
                (slug, row["name"], row["name_key"], row["department"],
                 get_college(row["department"])))
    moved, held = move_ratings(cur, PROFESSOR, entry_id, slug)
    resolve(cur, PROFESSOR, entry_id, "approved", slug)
    return f"Approved professor {clean(row['name'])} as {slug}: {_moved(moved, held)}"


def merge_professor(cur, entry_id, slug):
    load_pending(cur, PROFESSOR, entry_id)
    cur.execute("SELECT 1 FROM professors WHERE slug = %s", (slug,))
    if cur.fetchone() is None:
        raise ReviewError(f"No professor with slug {slug}")
    moved, held = move_ratings(cur, PROFESSOR, entry_id, slug)
    resolve(cur, PROFESSOR, entry_id, "merged", slug)
    return f"Merged professor {entry_id} into {slug}: {_moved(moved, held)}"


def reject_professor(cur, entry_id):
    return reject(cur, PROFESSOR, entry_id)


def approve_course(cur, entry_id):
    row = load_pending(cur, COURSE, entry_id)
    moved, held = move_ratings(cur, COURSE, entry_id, row["code"])
    resolve(cur, COURSE, entry_id, "approved", row["code"])
    return f"Approved course {clean(row['code'])}: {_moved(moved, held)}"


def merge_course(cur, entry_id, code):
    load_pending(cur, COURSE, entry_id)
    def query_one(sql, params):
        cur.execute(sql, params)
        return cur.fetchone()
    # The same codes the rating form accepts, including Banner-only ones.
    if not ratings.course_exists(code, query_one):
        raise ReviewError(f"No course with code {code}")
    moved, held = move_ratings(cur, COURSE, entry_id, code)
    resolve(cur, COURSE, entry_id, "merged", code)
    return f"Merged course {entry_id} into {code}: {_moved(moved, held)}"


def reject_course(cur, entry_id):
    return reject(cur, COURSE, entry_id)


def set_alias_status(cur, alias_id, status):
    try:
        alias_id = int(alias_id)
    except ValueError:
        raise ReviewError(f"Bad alias id {alias_id!r}") from None
    cur.execute("UPDATE professor_aliases SET status = %s WHERE id = %s AND status <> %s "
                "RETURNING alias_key, slug", (status, alias_id, status))
    row = cur.fetchone()
    if row is None:
        raise ReviewError(f"Alias {alias_id} is missing or already {status}")
    return f"Set alias {clean(row['alias_key'])} for {row['slug']} to {status}"


def approve_alias(cur, alias_id):
    return set_alias_status(cur, alias_id, "approved")


def reject_alias(cur, alias_id):
    return set_alias_status(cur, alias_id, "rejected")


def purge_ip(cur):
    def write(sql, params):
        cur.execute(sql, params)
    ratings.purge_ip_hashes(write, datetime.now(timezone.utc))
    return f"Cleared IP hashes older than {ratings.IP_HASH_DAYS} days and expired IP flags"


def clean(value):
    """Replace control characters (e.g. ANSI escapes) in submitted text before printing."""
    return "".join(c if c.isprintable() else "?" for c in str(value if value is not None else ""))


def list_pending(cur):
    cur.execute(
        "SELECT r.id, COALESCE(r.professor_slug, pp.name || ' (pending)') AS professor, "
        "COALESCE(r.course_code, pc.code || ' (pending)') AS course, r.term_label, r.rating, r.difficulty, "
        "r.hold_reasons, "
        "CASE WHEN r.agent_decision = 'reject' OR (r.agent_decision = 'escalate' "
        "AND r.agent_reviewed_at >= r.updated_at) THEN r.agent_decision END AS agent_decision, "
        "CASE WHEN r.agent_decision = 'reject' OR (r.agent_decision = 'escalate' "
        "AND r.agent_reviewed_at >= r.updated_at) THEN r.agent_reason END AS agent_reason, "
        "r.comment, r.created_at "
        "FROM survey_ratings r "
        "LEFT JOIN survey_pending_professors pp ON pp.id = r.pending_professor_id "
        "LEFT JOIN survey_pending_courses pc ON pc.id = r.pending_course_id "
        "WHERE r.status = 'held' ORDER BY r.created_at")
    held = cur.fetchall()
    print(f"Held ratings ({len(held)}):")
    for r in held:
        comment = clean((r["comment"] or "")[:80])
        print(f"  {str(r['id'])[:8]}  {clean(r['professor'])}  {clean(r['course'])}  "
              f"{clean(r['term_label'])}  {r['rating']}/5  difficulty {r['difficulty'] or '-'}/5  "
              f"[{clean(r['hold_reasons'])}]  "
              f"agent: {clean(r['agent_decision'] or '-')}"
              f"{' (' + clean(r['agent_reason']) + ')' if r['agent_reason'] else ''}  "
              f"{comment!r}  {str(r['created_at'])[:10]}")

    cur.execute(
        "SELECT p.id, p.name, p.name_key, p.department, count(r.id) AS n FROM survey_pending_professors p "
        "LEFT JOIN survey_ratings r ON r.pending_professor_id = p.id "
        "WHERE p.status = 'pending' GROUP BY p.id ORDER BY p.created_at")
    profs = cur.fetchall()
    print(f"Pending professors ({len(profs)}):")
    for p in profs:
        # name_key is accent-folded like professors.name_key; escape LIKE's wildcards.
        last = re.sub(r"([\\%_])", r"\\\1", p["name_key"].split()[-1])
        cur.execute("SELECT slug FROM professors WHERE name_key LIKE %s ORDER BY slug LIMIT 3",
                    ("% " + last,))
        similar = ", ".join(r["slug"] for r in cur.fetchall()) or "none"
        print(f"  {p['id']}  {clean(p['name'])}  {clean(p['department'])}  {p['n']} rating(s)  "
              f"same last name: {similar}")

    cur.execute(
        "SELECT c.id, c.code, c.name, c.agent_decision, c.agent_reason, count(r.id) AS n, "
        "EXISTS (SELECT 1 FROM course_catalog k WHERE k.code = c.code) AS in_catalog "
        "FROM survey_pending_courses c LEFT JOIN survey_ratings r ON r.pending_course_id = c.id "
        "WHERE c.status = 'pending' GROUP BY c.id ORDER BY c.created_at")
    courses = cur.fetchall()
    print(f"Pending courses ({len(courses)}):")
    for c in courses:
        print(f"  {c['id']}  {clean(c['code'])}  {clean(c['name'])}  {c['n']} rating(s)  "
              f"{'in' if c['in_catalog'] else 'not in'} course_catalog  "
              f"agent: {clean(c['agent_decision'] or '-')}"
              f"{' (' + clean(c['agent_reason']) + ')' if c['agent_reason'] else ''}")

    cur.execute("SELECT id, alias_key, slug, source FROM professor_aliases "
                "WHERE status = 'pending' ORDER BY created_at, id")
    aliases = cur.fetchall()
    print(f"Pending aliases ({len(aliases)}):")
    for a in aliases:
        print(f"  {a['id']}  {clean(a['alias_key'])} -> {clean(a['slug'])}  {clean(a['source'])}")
    return (f"{len(held)} held, {len(profs)} pending professors, {len(courses)} pending courses, "
            f"{len(aliases)} pending aliases")


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("purge-ip")
    for name in ("approve-rating", "reject-rating"):
        rating = sub.add_parser(name)
        rating.add_argument("ids", nargs="+")
        if name == "reject-rating":
            rating.add_argument("--abuse", action="store_true")
    approve = sub.add_parser("approve-professor")
    approve.add_argument("id")
    approve.add_argument("--slug")
    for name in ("merge-professor", "merge-course"):
        merge = sub.add_parser(name)
        merge.add_argument("id")
        merge.add_argument("target")
    for name in ("reject-professor", "approve-course", "reject-course", "remove-comment",
                 "approve-alias", "reject-alias"):
        sub.add_parser(name).add_argument("id")
    return parser.parse_args(argv)


def run(cur, args):
    command = args.command
    if command == "list":
        return list_pending(cur)
    if command == "purge-ip":
        return purge_ip(cur)
    if command == "reject-rating":
        return reject_rating(cur, *args.ids, abuse=args.abuse)
    if command == "approve-rating":
        return approve_rating(cur, *args.ids)
    if command == "approve-professor":
        return approve_professor(cur, args.id, args.slug)
    if command.startswith("merge-"):
        return COMMANDS[command](cur, args.id, args.target)
    return COMMANDS[command](cur, args.id)


COMMANDS = {
    "approve-rating": approve_rating, "reject-rating": reject_rating,
    "reject-professor": reject_professor, "merge-professor": merge_professor,
    "approve-course": approve_course, "merge-course": merge_course,
    "reject-course": reject_course, "remove-comment": remove_comment,
    "approve-alias": approve_alias, "reject-alias": reject_alias,
}
# Commands that can't change what a page shows; every other one bumps data_version
# so the site's caches drop pages that show (or no longer show) student reviews.
READ_ONLY_COMMANDS = ("list", "purge-ip")


def main(argv=None):
    args = parse_args(argv)
    conn = connect()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            summary = run(cur, args)
            if args.command not in READ_ONLY_COMMANDS:
                cur.execute(DATA_VERSION_SQL)
        conn.commit()
    except (ReviewError, psycopg2.DataError) as e:
        conn.rollback()
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
