"""Load NUBanner sections to CockroachDB.

Own tables, disjoint from everything backend/pipeline rebuilds. That separation
is the point: the pipeline swaps its tables in fresh every run,
while this history is expensive to re-fetch (one request per section) and
closed terms never change.

Three tables:

  banner_terms                 one row per term code ever scraped, with the
                               counts the next scrape's gates compare against
  banner_sections              one row per section (term_code, crn), TBA
                               sections included
  banner_section_instructors   one row per (term_code, crn, instructor)

A term is written as a unit: its old rows are deleted and the new ones inserted
in one transaction, after every gate in banner_scrape has passed. Nothing
outside the term being written is touched, so history accumulates.

`connect()` deliberately overrides the DSN's `sslmode=verify-full` with
`sslmode="require"` — the deployment does not distribute a root cert, so
verify-full fails outright before any query runs. This matches existing
precedent (`load_reddit_to_crdb.py`, `backend/pipeline/db.py`); do not "fix"
it back to the bare DSN.

Instructors for closed terms before --instructors-from (default Fall 2025)
came from a one-off import instead of ~7,000 Banner requests a term; those
terms are scraped sections-only here, and their instructor rows (source
'import') are left as they are. The import is not Banner data, so the matcher
reads only source = 'banner' rows; re-scraping those terms with instructors
(--instructors-from set lower) is what would bring them into the history.

Staging: --local-db PATH writes to a sqlite file instead of CockroachDB, so the
Banner traffic can happen once, offline from the database. --push-from PATH then
copies a staged file into CockroachDB without touching Banner.

Usage
-----
    python load_banner_to_crdb.py --selftest                 # offline DDL check
    python load_banner_to_crdb.py                            # open terms (weekly)
    python load_banner_to_crdb.py --backfill                 # closed terms since Fall 2021
    python load_banner_to_crdb.py --backfill --max-sections 30000 --since 202410
    python load_banner_to_crdb.py --local-db stage.db --backfill
    python load_banner_to_crdb.py --push-from stage.db

A stage pushed over prod is gated against prod's own counts, and a staged
sections-only term never touches prod's instructor rows.
"""

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import execute_values

from banner_client import BannerRateLimited, BannerRequestFailed
from banner_scrape import (DEFAULT_INSTRUCTORS_FROM, DEFAULT_SINCE_TERM,
                           MIN_SECTION_RATIO, SanityGateFailed, plan_terms,
                           scrape_term)

# CockroachDB runs SERIALIZABLE. A write that overlaps the live site's reads
# can be aborted with 40001 and has to be replayed by the client — the same
# hazard load_evidence_to_crdb.py added retries for after hitting it.
RETRYABLE_ERRORS = (psycopg2.errors.SerializationFailure,
                    psycopg2.errors.DeadlockDetected)
RETRY_ATTEMPTS = 6

# Backfill runs gentler than the weekly refresh: it is ~200k requests in total
# with no deadline, so there is no reason to run it at the measured optimum.
BACKFILL_CONCURRENCY = 2

# Exit status for a Banner 429/403 (EX_TEMPFAIL), distinct from a gate's 1, so
# the workflow can skip the finalize step's Banner traffic after one.
RATE_LIMITED_EXIT = 75

DDL = """
CREATE TABLE IF NOT EXISTS banner_terms (
    term_code            TEXT PRIMARY KEY,
    term_desc_raw        TEXT,
    term_label           TEXT NOT NULL,
    season               TEXT NOT NULL,
    season_group         TEXT NOT NULL,
    year                 INT NOT NULL,
    track                TEXT,
    view_only            BOOLEAN NOT NULL,   -- closed now, per the latest getTerms
    scraped_closed       BOOLEAN NOT NULL,   -- closed when its rows were scraped
    section_count        INT NOT NULL,
    attributed_sections  INT NOT NULL,
    instructor_count     INT NOT NULL,
    instructors_source   TEXT NOT NULL,      -- 'banner', or the one-off import's label
    first_seen_at        TIMESTAMPTZ,        -- first scraped while open, null for backfill
    scraped_at           TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS banner_sections (
    term_code            TEXT NOT NULL,
    crn                  TEXT NOT NULL,
    subject              TEXT,
    subject_course       TEXT,
    course_number        TEXT,
    section              TEXT,
    course_title         TEXT,
    campus               TEXT,
    instructional_method TEXT,
    schedule_type        TEXT,
    credit_hours_low     FLOAT,
    credit_hours_high    FLOAT,
    enrollment           INT,
    PRIMARY KEY (term_code, crn)
);
CREATE INDEX IF NOT EXISTS bsec_course ON banner_sections (subject_course);
CREATE TABLE IF NOT EXISTS banner_section_instructors (
    term_code            TEXT NOT NULL,
    crn                  TEXT NOT NULL,
    instructor_key       TEXT NOT NULL,
    instructor_name      TEXT NOT NULL,
    is_primary           BOOLEAN,
    source               TEXT NOT NULL DEFAULT 'banner',
    PRIMARY KEY (term_code, crn, instructor_key)
);
CREATE INDEX IF NOT EXISTS bsi_instructor ON banner_section_instructors (instructor_key);
CREATE TABLE IF NOT EXISTS banner_roster_duplicates (
    term_code            TEXT NOT NULL,
    instructor_key       TEXT NOT NULL,      -- >1 roster row normalizes to it
    PRIMARY KEY (term_code, instructor_key)
)
"""

TERM_COLUMNS = ("term_code", "term_desc_raw", "term_label", "season",
                "season_group", "year", "track", "view_only", "scraped_closed",
                "section_count", "attributed_sections", "instructor_count",
                "instructors_source", "first_seen_at")
SECTION_COLUMNS = ("term_code", "crn", "subject", "subject_course",
                   "course_number", "section", "course_title", "campus",
                   "instructional_method", "schedule_type",
                   "credit_hours_low", "credit_hours_high", "enrollment")
INSTRUCTOR_COLUMNS = ("term_code", "crn", "instructor_key", "instructor_name",
                      "is_primary", "source")
DUPLICATE_COLUMNS = ("term_code", "instructor_key")

# Same resolver flake and same answer as backend/pipeline/db.connect.
CONNECT_ATTEMPTS = 20


def connect(dsn, attempts=CONNECT_ATTEMPTS, sleep=time.sleep):
    """Open a CRDB connection, retrying the resolver flake.

    sslmode="require" overrides the DSN's verify-full, matching
    load_reddit_to_crdb.py and backend/pipeline/db.py — the deployment does not
    distribute a root cert, so verify-full fails outright.

    "could not translate host name" is a known flake on *.cockroachlabs.cloud;
    backend/pipeline/db.connect retries it the same way. Every connect in the
    loader and the matcher goes through here, so one flake can't skip a
    week's refresh. Any other connection error is raised at once.
    """
    for attempt in range(1, attempts + 1):
        try:
            return psycopg2.connect(dsn, sslmode="require")
        except psycopg2.OperationalError as e:
            if "could not translate host name" not in str(e) or attempt == attempts:
                raise
            print(f"  DNS lookup flaked; retrying ({attempt}/{attempts})...")
            sleep(3)


def with_retry(open_conn, work, attempts=RETRY_ATTEMPTS, sleep=time.sleep):
    """Run `work(cur)` in one transaction, replaying it whole on a 40001.

    The unit of replay is the transaction, not the statement: a term's delete
    and its inserts are only correct together, so re-committing without
    re-running `work` would leave the term half-written.

    A fresh connection per attempt: CockroachDB leaves the aborted
    connection's transaction unusable, so reusing it just fails again with a
    misleading error. Anything that is not retryable propagates immediately —
    a bug in the row builder must not be retried six times before surfacing.
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


def apply_ddl(cur):
    for stmt in DDL.split(";"):
        if stmt.strip():
            if isinstance(cur, sqlite3.Cursor):
                stmt = (stmt.replace("TIMESTAMPTZ", "TIMESTAMP")
                            .replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP"))
            cur.execute(stmt)


def known_terms(cur):
    """{term_code: (closed when last scraped, section_count)}.

    The first half drives plan_terms (a term last seen open needs one final
    scrape); the second is the section-count baseline for the drop gate.
    """
    cur.execute("SELECT term_code, scraped_closed, section_count FROM banner_terms")
    return {r[0]: (bool(r[1]), r[2]) for r in cur.fetchall()}


def _insert(cur, table, columns, rows, conflict=None):
    if not rows:
        return 0
    values = [tuple(r.get(c) for c in columns) for r in rows]
    if isinstance(cur, sqlite3.Cursor):
        verb = "INSERT OR REPLACE" if conflict else "INSERT"
        cur.executemany(
            f"{verb} INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' * len(columns))})", values)
    else:
        tail = ""
        if conflict:
            keys = {k.strip() for k in conflict.strip("()").split(",")}
            updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in keys)
            tail = f" ON CONFLICT {conflict} DO UPDATE SET {updates}, scraped_at = now()"
        execute_values(
            cur, f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s{tail}",
            values, page_size=2000)
    return len(rows)


def write_term(cur, term_code, parsed, desc_raw, scrape):
    """Replace one term's sections and instructors, and record its counts.

    Delete-then-insert is safe here, unlike in the single-season loader this
    replaced: the drop-gate baseline lives in banner_terms (updated in this
    same transaction), not in a count of the rows being deleted. And the gates
    have already passed before this runs.

    scrape["instructors"] is None for a sections-only scrape: the term's
    instructor rows (from the one-off import, or nothing yet) are left exactly as
    they are, and the term keeps its instructors_source and instructor counts.

    A section whose faculty lookup failed (scrape["failed_crns"]) keeps the
    instructor rows it already had: the gate tolerates a few failures, and
    deleting what last week attributed correctly would lose it for good once
    the term is closed. A closed term with any failed lookup is not marked
    scraped_closed, so the next finalize pass tries it again.

    A term whose last meeting has passed (scrape["ended"]) is stored as closed
    even though Banner has not marked it View Only yet.

    Returns (sections written, instructor rows written).
    """
    ph = _placeholder(cur)
    cur.execute(f"SELECT first_seen_at, instructors_source, attributed_sections, "
                f"instructor_count FROM banner_terms WHERE term_code = {ph}", (term_code,))
    prior = cur.fetchone()
    first_seen = prior[0] if prior else None
    if first_seen is None and not parsed["view_only"]:
        first_seen = datetime.now(timezone.utc).isoformat()

    closed = bool(parsed["view_only"] or scrape.get("ended"))
    failed = list(scrape.get("failed_crns") or [])
    sections_only = scrape["instructors"] is None
    if not sections_only:
        keep = ""
        if failed:
            keep = f" AND crn NOT IN ({', '.join([ph] * len(failed))})"
        cur.execute(f"DELETE FROM banner_section_instructors WHERE term_code = {ph}{keep}",
                    (term_code, *failed))
        cur.execute(f"DELETE FROM banner_roster_duplicates WHERE term_code = {ph}",
                    (term_code,))
        _insert(cur, "banner_roster_duplicates", DUPLICATE_COLUMNS,
                [{"term_code": term_code, "instructor_key": k}
                 for k in scrape.get("roster_duplicates") or []])
    cur.execute(f"DELETE FROM banner_sections WHERE term_code = {ph}", (term_code,))
    n_sections = _insert(cur, "banner_sections", SECTION_COLUMNS,
                         [{**s, "term_code": term_code} for s in scrape["sections"]])
    n_instructors = 0 if sections_only else _insert(
        cur, "banner_section_instructors", INSTRUCTOR_COLUMNS,
        [{"source": "banner", **r} for r in scrape["instructors"]])
    stats = dict(scrape["stats"])
    if sections_only:
        source = prior[1] if prior and prior[1] else "none"
        if prior:
            stats["attributed_sections"] = prior[2] or 0
            stats["instructor_count"] = prior[3] or 0
    else:
        source = "banner"
    _insert(cur, "banner_terms", TERM_COLUMNS, [{
        "term_code": term_code,
        "term_desc_raw": desc_raw,
        "term_label": parsed["label"],
        "season": parsed["season"],
        "season_group": parsed["season_group"],
        "year": parsed["year"],
        "track": parsed["track"],
        "view_only": closed,
        "scraped_closed": closed and not failed,
        "instructors_source": source,
        "first_seen_at": first_seen,
        **stats,
    }], conflict="(term_code)")
    return n_sections, n_instructors


def sync_view_only(cur, terms):
    """Copy getTerms' current View Only flags onto already-scraped terms.

    A term scraped while open keeps view_only = false until something says
    otherwise, and the matcher picks the teaching chip's season from that
    flag. Without this, the chip would keep naming last term for however long
    it takes the backfill to reach it. scraped_closed is left alone, so the
    backfill still owes that term its final re-scrape.
    """
    ph = _placeholder(cur)
    closed = []
    for t in terms:
        desc = (t.get("description") or "").lower()
        if "(view only)" in desc and t.get("code") is not None:
            closed.append(str(t["code"]))
    if not closed:
        return 0
    marks = ", ".join([ph] * len(closed))
    cur.execute(
        f"UPDATE banner_terms SET view_only = {ph} "
        f"WHERE view_only = {ph} AND term_code IN ({marks})",
        (True, False, *closed))
    return max(cur.rowcount or 0, 0)


def run(client, open_conn, mode, since_term=DEFAULT_SINCE_TERM,
        max_sections=None, dry_run=False,
        instructors_from=DEFAULT_INSTRUCTORS_FROM):
    """Scrape and write every term `plan_terms` picks. Returns (ok, failed).

    One transaction per term, so a backfill interrupted at term 40 keeps the
    39 it finished and resumes from 40. A term refused by a gate, or whose
    bootstrap, reset or pages failed, is skipped and the run carries on: in
    backfill so one bad 2017 CPS term can't block the rest, and in current
    mode so a future term with no schedule yet (or a CPS quarter code sorting
    above the semester) can't keep the live term from refreshing. Every
    refusal is still reported and makes the process exit non-zero. A rate
    limit is not caught: it stops the whole run.

    `max_sections` caps the work per run (checked between terms), so the
    backfill can be spread across scheduled runs instead of one 6-hour job.

    Closed terms before `instructors_from` are scraped sections-only. Open
    terms always get instructors — they feed the live teaching chip.
    """
    conn = open_conn()
    try:
        cur = conn.cursor()
        apply_ddl(cur)
        conn.commit()
        known = known_terms(cur)
    finally:
        conn.close()

    terms = client.get_terms()
    if not terms:
        raise SanityGateFailed("getTerms returned nothing")
    desc_by_code = {str(t.get("code")): t.get("description") for t in terms}
    plan = plan_terms(terms, {c: v for c, (v, _) in known.items()}, mode, since_term)
    print(f"{mode}: {len(plan)} term(s) to scrape")

    ok, failed, done_sections = [], [], 0
    for code, parsed in plan:
        if max_sections is not None and done_sections >= max_sections:
            print(f"section budget of {max_sections} reached — "
                  f"{len(plan) - len(ok) - len(failed)} term(s) left for the next run")
            break
        try:
            client.bootstrap(code)
            with_instructors = (not parsed["view_only"]
                                or int(code) >= int(instructors_from))
            scrape = scrape_term(client, code,
                                 previous_count=(known.get(code) or (None, None))[1],
                                 view_only=parsed["view_only"],
                                 with_instructors=with_instructors)
        except (SanityGateFailed, BannerRequestFailed) as e:
            print(f"GATE {e}", file=sys.stderr)
            failed.append(code)
            continue
        done_sections += scrape["stats"]["section_count"]
        if dry_run:
            print(f"{parsed['label']} [{code}]: dry run — not writing "
                  f"{scrape['stats']['section_count']} sections")
        else:
            n_sec, n_ins = with_retry(
                open_conn, lambda c, code=code, parsed=parsed, scrape=scrape:
                write_term(c, code, parsed, desc_by_code.get(code), scrape))
            print(f"{parsed['label']} [{code}]: wrote {n_sec} sections, "
                  + (f"{n_ins} instructor rows" if scrape["instructors"] is not None
                     else "instructor rows left as they are"))
        ok.append(code)

    if mode == "current" and not dry_run:
        n = with_retry(open_conn, lambda c: sync_view_only(c, terms))
        if n:
            print(f"marked {n} previously-open term(s) as View Only")
    return ok, failed


STAGED_TABLES = (("banner_terms", TERM_COLUMNS),
                 ("banner_sections", SECTION_COLUMNS),
                 ("banner_section_instructors", INSTRUCTOR_COLUMNS))


# push carries the stage's scraped_at; write_term leaves it to the column default.
PUSH_TERM_COLUMNS = TERM_COLUMNS + ("scraped_at",)


def _as_utc(value):
    """A scraped_at as an aware UTC datetime, or None.

    sqlite hands back text ("2026-10-01 12:00:00", UTC, from CURRENT_TIMESTAMP)
    and psycopg2 an aware datetime; naive values are taken as UTC.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def push(stage_path, open_conn):
    """Copy a staged sqlite file into CockroachDB, one transaction per term.

    No Banner traffic: everything comes from the file. Each term is replaced
    whole, like write_term, so pushing the same file twice is a no-op and
    pushing after a partial earlier push finishes the job. banner_terms is
    written last in each transaction, so a term only counts as present once
    its rows are.

    A term staged sections-only (instructors_source other than 'banner') has
    no instructor rows to put back, so prod's are left exactly as they are and
    the term keeps prod's instructors_source and counts, as write_term does.

    The stage's own gates ran against the stage's baseline, which a fresh
    file doesn't have, so each term is gated again against prod: a staged
    term more than MIN_SECTION_RATIO below prod's section count, an open
    snapshot over a term prod already holds as closed, or a scrape older than
    the one prod holds (an old stage pushed after a newer weekly run) is
    refused. Returns non-zero if any term was refused.

    Each term keeps the stage's scraped_at, not the push time: the chip's
    staleness check reads it, and an old stage must not look fresh.
    """
    stage = sqlite3.connect(stage_path)
    codes = [r[0] for r in stage.execute(
        "SELECT term_code FROM banner_terms ORDER BY term_code")]
    if not codes:
        raise SystemExit(f"{stage_path}: no terms staged")
    staged_tables = {r[0] for r in stage.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}

    conn = open_conn()
    try:
        cur = conn.cursor()
        apply_ddl(cur)
        conn.commit()
        cur.execute("SELECT term_code, section_count, scraped_closed, instructors_source, "
                    "attributed_sections, instructor_count, scraped_at FROM banner_terms")
        prod = {r[0]: r[1:] for r in cur.fetchall()}
    finally:
        conn.close()

    def rows(table, columns, code):
        if table not in staged_tables:     # a stage file from before the table existed
            return []
        cur = stage.execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE term_code = ?", (code,))
        return [dict(zip(columns, r)) for r in cur.fetchall()]

    def as_bool(rows_, *fields):
        for r in rows_:
            for f in fields:
                if r.get(f) is not None:
                    r[f] = bool(r[f])
        return rows_

    total, refused = 0, []
    for code in codes:
        terms = as_bool(rows("banner_terms", PUSH_TERM_COLUMNS, code),
                        "view_only", "scraped_closed")
        term = terms[0]
        staged_at = _as_utc(term["scraped_at"])
        term["scraped_at"] = staged_at.isoformat() if staged_at else None
        prior = prod.get(code)
        if prior:
            prod_at = _as_utc(prior[5])
            if prod_at and (staged_at is None or staged_at < prod_at):
                print(f"REFUSED {code}: staged scrape from {staged_at or 'an unknown time'} is "
                      f"older than prod's from {prod_at} — a stale stage", file=sys.stderr)
                refused.append(code)
                continue
            prod_count, prod_closed = prior[0] or 0, bool(prior[1])
            if term["section_count"] < prod_count * MIN_SECTION_RATIO:
                print(f"REFUSED {code}: staged {term['section_count']} sections against "
                      f"prod's {prod_count} — a stale or truncated stage", file=sys.stderr)
                refused.append(code)
                continue
            if prod_closed and not term["scraped_closed"]:
                print(f"REFUSED {code}: prod holds the closed term's final scrape; the "
                      f"stage only has an open snapshot", file=sys.stderr)
                refused.append(code)
                continue

        with_instructors = term["instructors_source"] == "banner"
        sections = rows("banner_sections", SECTION_COLUMNS, code)
        instructors = as_bool(rows("banner_section_instructors", INSTRUCTOR_COLUMNS, code),
                              "is_primary") if with_instructors else []
        duplicates = rows("banner_roster_duplicates", DUPLICATE_COLUMNS, code) \
            if with_instructors else []
        if not with_instructors and prior:
            term.update(instructors_source=prior[2], attributed_sections=prior[3],
                        instructor_count=prior[4])

        def work(cur, code=code, terms=terms, sections=sections, instructors=instructors,
                 duplicates=duplicates, with_instructors=with_instructors):
            ph = _placeholder(cur)
            tables = ("banner_sections", "banner_terms")
            if with_instructors:
                tables = ("banner_section_instructors", "banner_roster_duplicates") + tables
            for table in tables:
                cur.execute(f"DELETE FROM {table} WHERE term_code = {ph}", (code,))
            _insert(cur, "banner_sections", SECTION_COLUMNS, sections)
            if with_instructors:
                _insert(cur, "banner_section_instructors", INSTRUCTOR_COLUMNS, instructors)
                _insert(cur, "banner_roster_duplicates", DUPLICATE_COLUMNS, duplicates)
            _insert(cur, "banner_terms",
                    PUSH_TERM_COLUMNS if terms[0]["scraped_at"] else TERM_COLUMNS, terms)
            return len(sections)

        n = with_retry(open_conn, work)
        total += n
        print(f"pushed {code}: {n} sections, "
              + (f"{len(instructors)} instructor rows" if with_instructors
                 else "instructor rows left as they are"))
    print(f"pushed {len(codes) - len(refused)} terms, {total} sections"
          + (f"; refused {len(refused)} ({', '.join(refused)})" if refused else ""))
    return 1 if refused else 0


def sqlite_opener(path):
    def open_conn():
        conn = sqlite3.connect(path)
        return conn
    return open_conn


def selftest():
    """Run the DDL and one term write against in-memory sqlite. No network, no CRDB."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    apply_ddl(cur)
    parsed = {"label": "Fall 2026", "season": "Fall", "season_group": "Fall",
              "year": 2026, "track": "Semester", "view_only": False}
    scrape = {"sections": [{c: "x" for c in SECTION_COLUMNS}],
              "instructors": [{c: "x" for c in INSTRUCTOR_COLUMNS}],
              "stats": {"section_count": 1, "attributed_sections": 1,
                        "instructor_count": 1}}
    write_term(cur, "x", parsed, "Fall 2026 Semester", scrape)
    for table in ("banner_terms", "banner_sections", "banner_section_instructors"):
        assert cur.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1, table
    print("selftest OK: DDL applies and a term write round-trips")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scrape and load NUBanner sections")
    ap.add_argument("--selftest", action="store_true", help="offline DDL check, then exit")
    ap.add_argument("--backfill", action="store_true",
                    help="closed terms not yet stored, newest first (default: open terms)")
    ap.add_argument("--since", default=DEFAULT_SINCE_TERM,
                    help=f"earliest term code to backfill (default {DEFAULT_SINCE_TERM}, Fall 2021)")
    ap.add_argument("--instructors-from", default=DEFAULT_INSTRUCTORS_FROM,
                    help="closed terms before this code are scraped sections-only "
                         f"(default {DEFAULT_INSTRUCTORS_FROM}, Fall 2025)")
    ap.add_argument("--max-sections", type=int,
                    help="stop starting new terms after this many sections")
    ap.add_argument("--concurrency", type=int,
                    help="parallel faculty lookups (default 2 current, "
                         f"{BACKFILL_CONCURRENCY} backfill)")
    ap.add_argument("--dry-run", action="store_true", help="scrape and gate, write nothing")
    ap.add_argument("--local-db", help="write to this sqlite file instead of CockroachDB")
    ap.add_argument("--push-from", help="copy a staged sqlite file into CockroachDB, then exit")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.local_db:
        open_conn = sqlite_opener(args.local_db)
    else:
        dsn = os.environ.get("CRDB_DATABASE_URL")
        if not dsn:
            print("CRDB_DATABASE_URL is not set", file=sys.stderr)
            return 1
        open_conn = lambda: connect(dsn)  # noqa: E731

    if args.push_from:
        if args.local_db:
            print("--push-from copies into CockroachDB; drop --local-db", file=sys.stderr)
            return 1
        return push(args.push_from, open_conn)

    from banner_api import WEEKLY_CONCURRENCY
    from banner_client import BannerClient

    mode = "backfill" if args.backfill else "current"
    concurrency = args.concurrency or (BACKFILL_CONCURRENCY if args.backfill
                                       else WEEKLY_CONCURRENCY)
    try:
        ok, failed = run(BannerClient(concurrency=concurrency), open_conn,
                         mode, since_term=args.since, max_sections=args.max_sections,
                         dry_run=args.dry_run, instructors_from=args.instructors_from)
    except BannerRateLimited as e:
        # Terms finished before this were committed; the rest wait for next week.
        print(f"RATE LIMITED {e}", file=sys.stderr)
        return RATE_LIMITED_EXIT
    print(f"{mode}: {len(ok)} term(s) loaded, {len(failed)} refused by a gate"
          + (f" ({', '.join(failed)})" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
