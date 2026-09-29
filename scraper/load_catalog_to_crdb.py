"""Load the NEU academic catalog scrape to CockroachDB.

Own tables, disjoint from everything precompute.py drops — the same separation
load_banner_to_crdb.py keeps, and here it is not optional. `precompute.py`
rebuilds `course_catalog` wholesale (build into `_new`, then swap), so any
column written onto that table is destroyed by the next run with
REFRESH_TRACE=true. Catalog fields therefore live in `catalog_courses`, and
merging them into the course page is a read-side join, not a column graft.

NUpath is a child table rather than an array column for two reasons: the
payoff query is "every NCAD course ranked by TRACE score", which wants an
index on the attribute, and the tests run on sqlite, which has no arrays.

`connect()` overrides the DSN's `sslmode=verify-full` with `sslmode="require"`,
matching load_banner_to_crdb.py:78, load_reddit_to_crdb.py:134 and
precompute.py:37 — the deployment distributes no root cert, so verify-full
fails before any query runs. Do not "fix" it back to the bare DSN.

Usage
-----
    python load_catalog_to_crdb.py --selftest        # offline DDL + row build, then exit
    python load_catalog_to_crdb.py                   # load the default scrape JSON
    python load_catalog_to_crdb.py --json path.json --dry-run
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time

import psycopg2
from psycopg2.extras import execute_values

# Same hazard as the Banner loader: CockroachDB runs SERIALIZABLE and a write
# overlapping the live site's reads can be aborted with 40001.
RETRYABLE_ERRORS = (psycopg2.errors.SerializationFailure,
                    psycopg2.errors.DeadlockDetected)
RETRY_ATTEMPTS = 6

DEFAULT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "..", "RateMyHusky-data", "catalog_courses.json")
EDITION_STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "catalog_edition.json")

MIN_COURSE_RATIO = 0.9      # >10% fewer courses than the loaded table aborts
PRUNE_BATCH = 500           # codes per DELETE; the catalog is ~8,000 rows

# The catalog's typography is not what a student types. Normalising these for
# search only — `name` keeps the real glyphs, because the page displays it.
PUNCTUATION = {
    "’": "'", "‘": "'",      # curly single quotes
    "“": '"', "”": '"',      # curly double quotes
    "–": "-", "—": "-",      # en dash, em dash
    "…": "...",
}

# Courses that exist as registration bookkeeping rather than as classes. TRACE
# never surveys them, so they would otherwise arrive as several thousand
# permanently unrated pages — 849 of them titled "Elective".
#
# The rule matches the *whole* title, not a prefix. Measured over the 7,966
# scraped courses using a TRACE rating as ground truth for "a real class was
# taught": a prefix rule flags 62 rated courses ("Research Methods and
# Scientific Writing", "Project Management"), whole-title matching flags none.
#
# Only titles TRACE has rated *zero* times are listed. Deliberately absent:
# Topics (11 rated), Thesis (4), Special Topics (3), Seminar (2), Capstone (1),
# Practicum (1) — all generic-sounding and all real classes somewhere.
PLACEHOLDER_TITLES = frozenset({
    "elective", "research", "directed study", "independent study",
    "project", "internship",
})
PLACEHOLDER_PREFIXES = ("dissertation", "thesis continuation",
                        "candidacy continuation", "continuation")
# The x99x block is registration scaffolding — electives, co-op, directed
# study. 1,103 codes, of which TRACE has rated 11, so this is the one part of
# the rule with known false positives; see is_placeholder's docstring.
PLACEHOLDER_CODE = re.compile(r"\d99\d$")

DDL = """
CREATE TABLE IF NOT EXISTS catalog_courses (
    code          TEXT PRIMARY KEY,
    subject       TEXT,
    number        TEXT,
    name          TEXT,
    department    TEXT,
    credit_hours  TEXT,
    credit_min    FLOAT,
    credit_max    FLOAT,
    description   TEXT,
    prerequisites TEXT,
    corequisites  TEXT,
    search_text   TEXT,
    subject_slug  TEXT,
    catalog_year  TEXT,
    is_placeholder BOOL NOT NULL DEFAULT false,
    scraped_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cc_subject ON catalog_courses (subject);
CREATE INDEX IF NOT EXISTS cc_department ON catalog_courses (department);
CREATE INDEX IF NOT EXISTS cc_real ON catalog_courses (is_placeholder);
CREATE TABLE IF NOT EXISTS catalog_nupath (
    code      TEXT NOT NULL,
    attribute TEXT NOT NULL,
    PRIMARY KEY (code, attribute)
);
CREATE INDEX IF NOT EXISTS cn_attribute ON catalog_nupath (attribute)
"""

COLUMNS = ("code", "subject", "number", "name", "department", "credit_hours",
           "credit_min", "credit_max", "description", "prerequisites",
           "corequisites", "search_text", "subject_slug", "catalog_year",
           "is_placeholder")


class SanityGateFailed(RuntimeError):
    """A gate refused the load. Nothing has been written."""


def connect(dsn):
    return psycopg2.connect(dsn, sslmode="require")


def with_retry(open_conn, work, attempts=RETRY_ATTEMPTS, sleep=time.sleep):
    """Run `work(cur)` in one transaction, replaying it whole on a 40001.

    The unit of replay is the transaction: this loader pairs an upsert with a
    prune that is only correct against that same upsert, so re-committing
    without re-running `work` would leave the table half-updated.
    """
    for attempt in range(1, attempts + 1):
        conn = open_conn()
        try:
            result = work(conn.cursor())
            conn.commit()
            return result
        except RETRYABLE_ERRORS:
            try:
                conn.rollback()
            except Exception:      # the connection may already be unusable
                pass
            if attempt == attempts:
                raise
            sleep(0.1 * 2 ** attempt)
        finally:
            conn.close()


def _placeholder(cur):
    """sqlite uses ?, psycopg2 uses %s. The tests run on sqlite."""
    return "?" if isinstance(cur, sqlite3.Cursor) else "%s"


def normalize_text(text):
    """Fold the catalog's typography onto what a keyboard produces."""
    if not text:
        return ""
    for fancy, plain in PUNCTUATION.items():
        text = text.replace(fancy, plain)
    return " ".join(text.split()).lower()


def is_placeholder(code, name):
    """True when the row is registration bookkeeping, not a class.

    Advisory, not authoritative. The flag is derived from the title and code
    alone, because this table deliberately knows nothing about ratings — they
    live in TRACE, which precompute.py owns. The consumer's rule should
    therefore be `NOT is_placeholder OR the course has ratings`: that override
    costs nothing and covers the 11 x99x codes TRACE has actually rated, plus
    any future one this rule has not seen.
    """
    title = " ".join((name or "").split()).lower().rstrip(".")
    return (title in PLACEHOLDER_TITLES
            or title.startswith(PLACEHOLDER_PREFIXES)
            or bool(PLACEHOLDER_CODE.search(code)))


def build_rows(scraped, catalog_year):
    """(course rows, nupath pairs) from catalog_scrape.py's JSON."""
    departments = {s["slug"]: s["department"] for s in scraped.get("subjects", [])}

    rows, nupath = [], []
    for course in scraped["courses"]:
        code = course["code"]
        # search_text mirrors precompute.build_course_rows: lowercase, space
        # joined, code first. The description and the NUpath labels are the new
        # part — "management" has never matched "Financial Mngmnt", and nothing
        # has ever made a course findable by the requirement it satisfies.
        rows.append({
            "code": code,
            "subject": course["subject"],
            "number": course["number"],
            "name": course["name"],
            "department": departments.get(course["subject_slug"], ""),
            "credit_hours": course["credit_hours"],
            "credit_min": course["credit_min"],
            "credit_max": course["credit_max"],
            "description": course["description"],
            "prerequisites": course["prerequisites"],
            "corequisites": course["corequisites"],
            "search_text": " ".join(filter(None, [
                normalize_text(code),
                normalize_text(course["name"]),
                normalize_text(course["description"]),
                normalize_text(" ".join(course["nupath"])),
            ])),
            "subject_slug": course["subject_slug"],
            "catalog_year": catalog_year,
            "is_placeholder": is_placeholder(code, course["name"]),
        })
        for attribute in course["nupath"]:
            nupath.append((code, attribute))
    return rows, nupath


def previous_count(cur):
    """Rows already loaded — the sanity-gate baseline. 0 on a first run."""
    cur.execute("SELECT count(*) FROM catalog_courses")
    return cur.fetchone()[0]


def check_gates(rows, previous):
    """Refuse a load that would shrink the catalog. Nothing is written first."""
    if not rows:
        raise SanityGateFailed("scrape holds 0 courses")
    if previous and len(rows) < previous * MIN_COURSE_RATIO:
        raise SanityGateFailed(
            f"{len(rows)} courses vs {previous} previously loaded "
            f"({len(rows) / previous:.0%}) — below the {MIN_COURSE_RATIO:.0%} floor")


def upsert_courses(cur, rows):
    """Upsert by code. Never delete-then-insert.

    A delete-first loader would destroy the row-count baseline the gate
    compares against before the next run could read it.
    """
    if not rows:
        return 0
    values = [tuple(r[c] for c in COLUMNS) for r in rows]
    updates = ", ".join(f"{c} = excluded.{c}" for c in COLUMNS if c != "code")
    if isinstance(cur, sqlite3.Cursor):
        cur.executemany(
            f"INSERT INTO catalog_courses ({', '.join(COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(COLUMNS))}) "
            f"ON CONFLICT (code) DO UPDATE SET {updates}",
            values)
    else:
        execute_values(
            cur,
            f"INSERT INTO catalog_courses ({', '.join(COLUMNS)}) VALUES %s "
            f"ON CONFLICT (code) DO UPDATE SET {updates}, scraped_at = now()",
            values, page_size=2000)
    return len(rows)


def replace_nupath(cur, pairs, codes, batch=PRUNE_BATCH):
    """Rewrite the attributes of every course in this run.

    Delete-then-insert per code rather than upsert: an upsert can only add
    attributes, and attributes are removed — Writing Intensive is
    section-specific and moves between editions. A course that loses its last
    attribute must end with no rows, which an upsert can never produce.

    `codes` is every course in the run, not just the ones carrying an
    attribute. Deriving the clear-set from `pairs` looks equivalent and is not:
    a course that loses its *last* attribute appears in no pair, so its stale
    rows would survive every delete and it would keep a NUpath tag the catalog
    no longer gives it.
    """
    ph = _placeholder(cur)
    codes = sorted(set(codes))
    for i in range(0, len(codes), batch):
        chunk = codes[i:i + batch]
        cur.execute(
            f"DELETE FROM catalog_nupath WHERE code IN ({', '.join([ph] * len(chunk))})",
            chunk)
    if not pairs:
        return 0
    if isinstance(cur, sqlite3.Cursor):
        cur.executemany("INSERT INTO catalog_nupath (code, attribute) VALUES (?, ?)", pairs)
    else:
        execute_values(cur, "INSERT INTO catalog_nupath (code, attribute) VALUES %s",
                       pairs, page_size=2000)
    return len(pairs)


def prune_stale(cur, seen_codes, batch=PRUNE_BATCH):
    """Delete codes that left the catalog, and their attributes.

    Computed in Python and deleted in batches rather than `NOT IN (...)`: the
    catalog holds ~8,000 codes, and one statement carrying 8,000 bind
    parameters is how this breaks in production but not in tests.

    Deleting here is safe in a way it would not be against course_catalog —
    this table is only ever the catalog's own contents, so a course that leaves
    the catalog (ENGL 3467 did, mid-edition) loses its catalog fields while its
    TRACE ratings and its page are untouched.
    """
    ph = _placeholder(cur)
    cur.execute("SELECT code FROM catalog_courses")
    stale = sorted({r[0] for r in cur.fetchall()} - set(seen_codes))
    for i in range(0, len(stale), batch):
        chunk = stale[i:i + batch]
        marks = ", ".join([ph] * len(chunk))
        cur.execute(f"DELETE FROM catalog_courses WHERE code IN ({marks})", chunk)
        cur.execute(f"DELETE FROM catalog_nupath WHERE code IN ({marks})", chunk)
    return len(stale)


def read_catalog_year(path=EDITION_STATE):
    """The edition the watcher last recorded, stamped onto every row.

    Read rather than derived so a description can always be attributed to the
    catalog it came from — and so a load that happens before the watcher is
    re-recorded is visibly stamped with the old year.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)["edition"]
    except (OSError, KeyError, ValueError):
        return None


def selftest():
    """Offline: apply the DDL to sqlite and run a load through it end to end."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    for stmt in DDL.split(";"):
        if stmt.strip():
            cur.execute(stmt.replace("TIMESTAMPTZ", "TIMESTAMP")
                            .replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP"))

    scraped = {
        "subjects": [{"slug": "cs", "subject": "CS", "department": "Computer Science"}],
        "courses": [{
            "code": "CS3000", "subject": "CS", "number": "3000",
            "name": "Algorithms and Data", "credit_hours": "4 Hours",
            "credit_min": 4.0, "credit_max": 4.0, "description": "Introduces algorithms.",
            "prerequisites": "CS 2100", "corequisites": None,
            "nupath": ["Formal/Quant Reasoning"], "subject_slug": "cs",
        }],
    }
    rows, nupath = build_rows(scraped, catalog_year="2025-2026")
    codes = {r["code"] for r in rows}
    check_gates(rows, previous_count(cur))
    upsert_courses(cur, rows)
    replace_nupath(cur, nupath, codes)
    prune_stale(cur, codes)

    assert previous_count(cur) == 1, "course row did not land"
    assert cur.execute("SELECT count(*) FROM catalog_nupath").fetchone()[0] == 1
    print("selftest OK: DDL applies, rows build, upsert/prune round-trips")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Load the NEU catalog scrape to CockroachDB")
    ap.add_argument("--selftest", action="store_true", help="offline DDL check, then exit")
    ap.add_argument("--json", default=DEFAULT_JSON, help="catalog_scrape.py output")
    ap.add_argument("--dry-run", action="store_true", help="gate and report, write nothing")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    with open(args.json, encoding="utf-8") as fh:
        scraped = json.load(fh)

    catalog_year = read_catalog_year()
    if not catalog_year:
        print("Could not read the edition from catalog_edition.json; "
              "run catalog_edition.py --record first", file=sys.stderr)
        return 1

    rows, nupath = build_rows(scraped, catalog_year)
    print(f"{len(rows)} courses, {len(nupath)} NUpath rows, edition {catalog_year}")

    if args.dry_run:
        try:
            check_gates(rows, previous=0)
        except SanityGateFailed as gate:
            print(f"ABORTED: {gate}", file=sys.stderr)
            return 1
        print("Dry run: nothing written.")
        return 0

    dsn = os.environ.get("CRDB_DATABASE_URL")
    if not dsn:
        print("CRDB_DATABASE_URL is not set", file=sys.stderr)
        return 1

    conn = connect(dsn)
    try:
        cur = conn.cursor()
        for stmt in DDL.split(";"):
            if stmt.strip():
                cur.execute(stmt)
        conn.commit()
        baseline = previous_count(cur)
    finally:
        conn.close()

    try:
        check_gates(rows, baseline)
    except SanityGateFailed as gate:
        print(f"ABORTED: {gate}", file=sys.stderr)
        print("Nothing was written.", file=sys.stderr)
        return 1

    codes = {r["code"] for r in rows}

    def work(cur):
        upsert_courses(cur, rows)
        replace_nupath(cur, nupath, codes)
        return prune_stale(cur, codes)

    pruned = with_retry(lambda: connect(dsn), work)
    print(f"Loaded {len(rows)} courses ({baseline} before), pruned {pruned}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
