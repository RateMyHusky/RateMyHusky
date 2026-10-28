"""Review held survey ratings and new professors and courses (rating form, plan 3).

    python review_ratings.py list                       # held ratings, comments to read, pending professors and courses
    python review_ratings.py approve-rating ID [ID...]  # held -> accepted
    python review_ratings.py reject-rating ID [ID...]   # delete the rating
    python review_ratings.py approve-comment ID@TIME [ID@TIME...]  # show a comment, as list printed it
    python review_ratings.py reject-comment ID [ID...]  # drop a waiting comment, keep its rating
    python review_ratings.py remove-comment PUBLIC_ID   # take down a shown comment by the id a report carries
    python review_ratings.py approve-professor ID [--slug SLUG]
    python review_ratings.py merge-professor ID SLUG
    python review_ratings.py reject-professor ID
    python review_ratings.py approve-course ID
    python review_ratings.py merge-course ID CODE
    python review_ratings.py reject-course ID
    python review_ratings.py purge-ip                   # clear IP hashes older than 30 days

Rating ids may be the short id `list` prints. Each run is one transaction: it
commits at the end, and rolls back and exits 1 on a bad id or a non-pending
entry. Reads ORACLE_DATABASE_URL. `list` prints no hashes or network data.
A professor page's student numbers and reviews change within minutes, since
every command but list and purge-ip bumps data_version; the rest of the site
(cards, course pages, leaderboards) follows on the next pipeline run. Approving
a rating held as unverified_pair vouches for that professor teaching that
course, so later ratings of the pair aren't held for it.

A comment never shows until approve-comment, even on an accepted rating, and
an edit to its text waits again. approve-comment takes the ID@TIME `list`
printed next to the comment, and refuses when the row changed since then, so
an edit between reading and approving can't put unread text on the page. approve-rating counts the rating only: its
comment stays in the comments list until approved there too.

`list` shows each comment's model check (moderation_groq.py): flagged first,
then clean or not yet checked. The check only sorts the list; approving and
rejecting work the same either way, and both take the comment off
moderate_queue.py's queue. A comment the queue found blocked is flagged as
`blocked` and its rating held as moderation_block until a reviewer acts.
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


def reject_rating(cur, *ids):
    for rating_id in ids:
        cur.execute("DELETE FROM survey_ratings WHERE id::text LIKE %s AND status = 'held' "
                    "RETURNING id", (short_id_pattern(rating_id),))
        if len(cur.fetchall()) != 1:
            raise ReviewError(f"{rating_id} is not exactly one held rating")
    return f"Rejected {len(ids)} rating(s)"


def comment_version(rating_id, updated_at):
    """What `list` prints for approve-comment: the short id and the row's updated_at."""
    stamp = updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at)
    return f"{str(rating_id)[:8]}@{stamp}"


def approve_comment(cur, *versions):
    """Approve each comment as `list` printed it (ID@TIME). Any save since moves
    updated_at, so an edit in between fails here instead of going live unread."""
    for version in versions:
        rating_id, sep, stamp = version.partition("@")
        if not sep or not stamp:
            raise ReviewError(f"Give {version!r} as the ID@TIME list printed, so the text approved is the text read")
        try:
            datetime.fromisoformat(stamp)
        except ValueError:
            raise ReviewError(f"Bad time in {version!r}") from None
        # Off the queue too, so a moderate_queue.py run racing this can't hold the rating.
        cur.execute("UPDATE survey_ratings SET comment_status = 'approved', comment_next_check_at = NULL "
                    "WHERE id::text LIKE %s AND comment_status = 'pending' AND updated_at = %s::timestamptz "
                    "RETURNING id", (short_id_pattern(rating_id), stamp))
        if len(cur.fetchall()) != 1:
            raise ReviewError(f"{version} is not exactly one comment waiting for review as list printed it; "
                              "it may have been edited, so run list again")
    return f"Approved {len(versions)} comment(s)"


# Clears the comment and nothing else. A comment the device writes again waits in
# pending like any new one, so the rating needs no hold; and hold_reasons stays as
# it was, since a non-NULL one would take the rating out of the surge counts for
# good. comment_hash stays, so the same text from another device is held as a
# duplicate_comment.
_DROP_COMMENT_SQL = (
    "UPDATE survey_ratings SET comment = NULL, comment_status = NULL"
    + "".join(f", {c} = NULL" for c in ratings.CHECK_COLUMNS) + " ")


def reject_comment(cur, *ids):
    """Drop each waiting comment; its rating keeps counting."""
    for rating_id in ids:
        cur.execute(_DROP_COMMENT_SQL + "WHERE id::text LIKE %s AND comment_status = 'pending' RETURNING id",
                    (short_id_pattern(rating_id),))
        if len(cur.fetchall()) != 1:
            raise ReviewError(f"{rating_id} is not exactly one comment waiting for review")
    return f"Rejected {len(ids)} comment(s)"


def remove_comment(cur, review_id):
    """Drop the comment of the review whose public id (the one on the page and in
    a report) is review_id; the rating keeps counting. Needs RATING_SECRET.
    Clears it as reject_comment does."""
    secret = os.getenv("RATING_SECRET")
    if not secret:
        raise ReviewError("RATING_SECRET is needed to match a public review id")
    cur.execute("SELECT id FROM survey_ratings WHERE comment_status = 'approved'")
    matches = [str(r["id"]) for r in cur.fetchall() if survey_reviews.public_id(secret, r["id"]) == review_id]
    if len(matches) != 1:
        raise ReviewError(f"{review_id} is not exactly one shown review")
    cur.execute(_DROP_COMMENT_SQL + "WHERE id::text = %s RETURNING id", (matches[0],))
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


def purge_ip(cur):
    def write(sql, params):
        cur.execute(sql, params)
    ratings.purge_ip_hashes(write, datetime.now(timezone.utc))
    return f"Cleared IP hashes older than {ratings.IP_HASH_DAYS} days"


def clean(value):
    """Replace control characters (e.g. ANSI escapes) in submitted text before printing."""
    return "".join(c if c.isprintable() else "?" for c in str(value if value is not None else ""))


def check_label(check, reason):
    """How `list` shows a comment's model check."""
    if check == "review":
        return f"flagged: {clean(reason or 'review')}"
    if check == "allow":
        return "clean"
    return "not yet checked" + (f" ({clean(reason)})" if reason else "")


def list_pending(cur):
    cur.execute(
        "SELECT r.id, COALESCE(r.professor_slug, pp.name || ' (pending)') AS professor, "
        "COALESCE(r.course_code, pc.code || ' (pending)') AS course, r.term_label, r.rating, r.difficulty, "
        "r.hold_reasons, r.comment, r.created_at "
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
              f"{comment!r}  {str(r['created_at'])[:10]}")

    # The whole text, since approving it puts every word on the page.
    cur.execute(
        "SELECT r.id, COALESCE(r.professor_slug, pp.name || ' (pending)') AS professor, "
        "COALESCE(r.course_code, pc.code || ' (pending)') AS course, r.status, r.rating, r.comment, r.updated_at, "
        "r.comment_check, r.comment_check_reason "
        "FROM survey_ratings r "
        "LEFT JOIN survey_pending_professors pp ON pp.id = r.pending_professor_id "
        "LEFT JOIN survey_pending_courses pc ON pc.id = r.pending_course_id "
        "WHERE r.comment_status = 'pending' "
        "ORDER BY r.comment_check IS DISTINCT FROM 'review', r.updated_at")
    comments = cur.fetchall()
    print(f"Comments to review ({len(comments)}):")
    for r in comments:
        print(f"  {str(r['id'])[:8]}  {clean(r['professor'])}  {clean(r['course'])}  {r['rating']}/5  "
              f"rating {r['status']}  {check_label(r['comment_check'], r['comment_check_reason'])}  "
              f"{str(r['updated_at'])[:10]}\n      {clean(r['comment'])!r}\n"
              f"      approve-comment {comment_version(r['id'], r['updated_at'])}")

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
        "SELECT c.id, c.code, c.name, count(r.id) AS n, "
        "EXISTS (SELECT 1 FROM course_catalog k WHERE k.code = c.code) AS in_catalog "
        "FROM survey_pending_courses c LEFT JOIN survey_ratings r ON r.pending_course_id = c.id "
        "WHERE c.status = 'pending' GROUP BY c.id ORDER BY c.created_at")
    courses = cur.fetchall()
    print(f"Pending courses ({len(courses)}):")
    for c in courses:
        print(f"  {c['id']}  {clean(c['code'])}  {clean(c['name'])}  {c['n']} rating(s)  "
              f"{'in' if c['in_catalog'] else 'not in'} course_catalog")
    return (f"{len(held)} held, {len(comments)} comments to review, "
            f"{len(profs)} pending professors, {len(courses)} pending courses")


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("purge-ip")
    for name in ("approve-rating", "reject-rating", "approve-comment", "reject-comment"):
        sub.add_parser(name).add_argument("ids", nargs="+")
    approve = sub.add_parser("approve-professor")
    approve.add_argument("id")
    approve.add_argument("--slug")
    for name in ("merge-professor", "merge-course"):
        merge = sub.add_parser(name)
        merge.add_argument("id")
        merge.add_argument("target")
    for name in ("reject-professor", "approve-course", "reject-course", "remove-comment"):
        sub.add_parser(name).add_argument("id")
    return parser.parse_args(argv)


def run(cur, args):
    command = args.command
    if command == "list":
        return list_pending(cur)
    if command == "purge-ip":
        return purge_ip(cur)
    if command in ("approve-rating", "reject-rating", "approve-comment", "reject-comment"):
        return COMMANDS[command](cur, *args.ids)
    if command == "approve-professor":
        return approve_professor(cur, args.id, args.slug)
    if command.startswith("merge-"):
        return COMMANDS[command](cur, args.id, args.target)
    return COMMANDS[command](cur, args.id)


COMMANDS = {
    "approve-rating": approve_rating, "reject-rating": reject_rating,
    "approve-comment": approve_comment, "reject-comment": reject_comment,
    "reject-professor": reject_professor, "merge-professor": merge_professor,
    "approve-course": approve_course, "merge-course": merge_course,
    "reject-course": reject_course, "remove-comment": remove_comment,
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
