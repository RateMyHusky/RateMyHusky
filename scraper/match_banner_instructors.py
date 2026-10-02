"""Match Banner instructors to professors_catalog and build the derived tables.

  professor_teaching          the current season's chip, one row per professor
  banner_unmatched            this season's instructors with no catalog match
  banner_course_instructors   every (course, instructor) pair across all
                              stored terms — see banner_history
  banner_course_offerings     one row per course: when it runs, class size,
                              how many people teach it, credits, whether
                              it is on the current schedule

Name-based, because there is nothing else. rmp_professors.csv carries no
email column, and Banner itself only supplies one
~15% of the time (measured 2026-08-04). So identity on both sides is a
normalized name.

No fuzzy matching. Banner offers no department or subject signal at match time,
and a wrong match publishes a course on the wrong person's profile. Ambiguity
is recorded, never resolved.

Usage
-----
    python match_banner_instructors.py
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")))

from banner_api import NON_PLACE_CAMPUSES, NON_TEACHING_SCHEDULE_TYPES  # noqa: E402,F401
from banner_history import (build_course_instructors,  # noqa: E402
                            build_course_offerings, rename_candidates)
from prof_aliases import ALIAS_MAP  # noqa: E402

# One definition of how to reach CRDB, shared with the loader: sslmode must
# override the DSN's verify-full or the connection fails outright. with_retry
# comes from the same place so both write paths replay a 40001 identically.
from load_banner_to_crdb import connect, with_retry  # noqa: E402

# A run must keep at least this share of the previous run's matches. Not a
# share of Banner: the catalog only holds professors with an RMP page, so most
# Banner instructors legitimately match nothing (36% matched on Fall 2026,
# measured 2026-10-02). A broken run — an empty or mismatched catalog index, a
# name_key normalization change — shows up as a collapse against last week.
MIN_KEPT_RATIO = 0.5

# Banner-only name variants -> the catalog name_key they belong to.
#
# Separate from prof_aliases.ALIAS_MAP on purpose. ALIAS_MAP is site-wide —
# the backend resolves name_keys through it (professor_full.py, denylist.py) —
# so an entry there changes how every page finds a professor. Every key below
# is a spelling only *NUBanner* uses — none of them appears as a live catalog
# row (checked against production 2026-08-04 and 2026-10-02) — so in ALIAS_MAP
# they would make the whole site depend on Banner's spelling. Here they cost
# nothing outside the matcher and land on a matcher re-run alone: no re-scrape,
# no catalog rebuild.
#
# Curated, never fuzzy. Each was verified individually against the catalog; the
# ~100 near-misses that rapidfuzz also surfaced are *different people* (a police
# chief vs a science dean, ROTC vs chemistry, a PhD student vs her own
# professor), which is why match_one still has no similarity threshold.
#
# Deliberately excluded, both genuinely uncertain:
#   "kurdea lyon"  -> catalog has "lyon kurdea": a first/last swap where it is
#                     unclear which source is right.
#   "mimi wan"     -> catalog has "mimi wang": one letter, and Wan and Wang are
#                     both common surnames, so this may be two people.
BANNER_ALIASES = {
    # Nicknames the catalog stores in the opposite form
    "philip gasper": "phil gasper",
    "tom williams": "thomas williams",
    "david hagen": "dave hagen",
    # Banner carries a name part the catalog lacks (or vice versa)
    "melissa liriano-ng": "melissa liriano",
    "elisabeth neville ambler": "elisabeth neville",
    "mary ellen dronitsky": "mary dronitsky",
    "wan yee yvonne leung": "yvonne leung",
    "johan bonilla": "johan bonilla castro",
    "thiago santos": "thiago monteiro araujo dos santos",
    # Banner carries a middle name or second surname the RMP-built catalog
    # drops. Each was the only Banner instructor and the only catalog row with
    # that first + last name, and Banner's subjects agree with the catalog
    # department (checked 2026-10-02 on Fall 2026).
    "alina ionica lungeanu": "alina lungeanu",              # MGMT / Business
    "ayse bilge yildirim": "ayse yildirim",                 # PSYC / Psychology
    "bob de schutter": "bob schutter",                      # GAME / Game Design
    "caitlin smith rapoport": "caitlin rapoport",           # THTR / Theater
    "daniel noemi voionmaa": "daniel voionmaa",             # SPNS / unspecified
    "heidi kevoe feldman": "heidi feldman",                 # COMM / Communication
    "jose angel martinez-lorenzo": "jose martinez-lorenzo", # EECE / Engineering
    "kristen mathieu gonzalez": "kristen gonzalez",         # NRSG / Nursing
    "leila keyvani someh": "leila someh",                   # GE / Mechanical Eng
    "maria elena villar": "maria villar",                   # COMM / Communication
    "mariana valencia mestre": "mariana mestre",            # ENVR / Environmental Sci
    "mohammad mohammad dehghani dehghani": "mohammad dehghani",  # IE / Engineering
    "monica baraldi borgida": "monica borgida",             # MGT / Business Admin
    "najla miranda mouchrek": "najla mouchrek",             # ARTG / Fine Arts
    "naveen naik sapavath": "naveen sapavath",              # EECE / Engineering
    "noor ul sabah ali": "noor ali",                        # EDU / Education
    "pablo boixeda alvarez": "pablo alvarez",               # MATH / Mathematics
    "pedro miguel cruz": "pedro cruz",                      # ARTG / Fine Arts
    "victoria vera preys": "victoria preys",                # FINA / Business
    "zorana matic isautier": "zorana isautier",             # ARCH / Architecture
    # One side is misspelled; Banner is the more likely correct spelling
    "georgia thoidis": "georgia theodis",
    "kari thierer": "kari theirer",
    # An apostrophe inside a *first* name. Distinct from the html.unescape fix
    # in banner_api: there Banner was escaped and the catalog was clean, here
    # Banner is clean and the catalog dropped the punctuation.
    "mai'a cross": "maia cross",
    # The catalog's own copy is truncated mid-word at 15 chars — a bad RMP
    # source record, not a field-width cap (16- and 17-char first names exist).
    # ALIAS_MAP already points "sriram rajagopalan" at the same truncated key.
    "sriramasundararajan rajagopalan": "sriramasundarar rajagopalan",
}


class MatchGateFailed(RuntimeError):
    """The match rate looks like a broken run, not a quiet season.

    Raised before any write, so professor_teaching / banner_unmatched for
    this term_desc are left exactly as they were — this exists specifically
    to stop write_results' same-season DELETE from being reached on a
    collapsed run.
    """


TEACHING_DDL = """
CREATE TABLE IF NOT EXISTS professor_teaching (
    professor_slug TEXT NOT NULL,
    name_key       TEXT NOT NULL,
    term_desc      TEXT NOT NULL,
    term_codes     TEXT NOT NULL,
    course_codes   TEXT NOT NULL,
    campuses       TEXT,            -- "|"-separated: campus names contain commas
                                    -- ("Oakland, CA", "Vancouver, Canada")
    match_method   TEXT NOT NULL,
    scraped_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (name_key, term_desc)
);
CREATE INDEX IF NOT EXISTS pt_slug ON professor_teaching (professor_slug)
"""

UNMATCHED_DDL = """
CREATE TABLE IF NOT EXISTS banner_unmatched (
    term_desc        TEXT NOT NULL,
    instructor_key   TEXT NOT NULL,
    instructor_name  TEXT,
    course_codes     TEXT,
    reason           TEXT NOT NULL,
    candidates       TEXT,
    scraped_at       TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (term_desc, instructor_key)
)
"""

HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS banner_course_instructors (
    subject_course   TEXT NOT NULL,
    instructor_key   TEXT NOT NULL,
    instructor_name  TEXT,
    professor_slug   TEXT,              -- null when unmatched or ambiguous
    name_key         TEXT,
    match_method     TEXT NOT NULL,
    terms_taught     INT NOT NULL,
    sections         INT NOT NULL,
    first_term_code  TEXT NOT NULL,
    last_term_code   TEXT NOT NULL,
    last_term_label  TEXT NOT NULL,
    recent_terms     TEXT,              -- newest first, comma-joined, at most 6
    avg_enrollment   FLOAT,             -- closed terms only
    was_primary      BOOLEAN,
    campuses         TEXT,              -- "|"-joined
    methods          TEXT,              -- "|"-joined
    PRIMARY KEY (subject_course, instructor_key)
);
CREATE INDEX IF NOT EXISTS bci_slug ON banner_course_instructors (professor_slug);
CREATE TABLE IF NOT EXISTS banner_course_offerings (
    subject_course        TEXT PRIMARY KEY,
    subject               TEXT,
    course_title          TEXT,
    first_term_code       TEXT NOT NULL,
    last_term_code        TEXT NOT NULL,
    last_term_label       TEXT NOT NULL,
    terms_offered         INT NOT NULL,
    pattern               TEXT NOT NULL,
    fall_years            INT NOT NULL,
    spring_years          INT NOT NULL,
    summer_years          INT NOT NULL,
    pattern_window_years  INT NOT NULL,
    avg_sections_per_term FLOAT,
    avg_section_size      FLOAT,
    median_section_size   FLOAT,
    credit_hours          TEXT,
    instructor_count      INT NOT NULL,
    offered_now           TEXT           -- open term labels, comma-joined
);
CREATE TABLE IF NOT EXISTS banner_course_rename_candidates (
    old_code              TEXT NOT NULL,
    new_code              TEXT NOT NULL,
    title                 TEXT,
    old_last_term         TEXT,
    new_first_term_code   TEXT,
    same_subject          BOOLEAN,
    shared_instructors    TEXT,
    approved              BOOLEAN NOT NULL,
    PRIMARY KEY (old_code, new_code)
);
CREATE TABLE IF NOT EXISTS banner_course_renames (
    old_code              TEXT PRIMARY KEY,
    new_code              TEXT NOT NULL
)
"""

# Approved renumberings: old code -> the code it became. A course page for the
# new code shows the old code's history too, labelled with the old code; the
# old code's own page links forward. Curated, never fuzzy — the same rule as
# BANNER_ALIASES, for the same reason: a wrong entry puts another course's
# instructors and class sizes on a page. Approve from
# banner_course_rename_candidates, one pair at a time.
COURSE_RENAMES = {
}

# Whole-subject renames, applied to every code in the subject that has a
# same-numbered successor: {"AFAM": "AFCS"} maps AFAM1225 -> AFCS1225. Only
# pairs where the successor code actually exists are written.
SUBJECT_RENAMES = {
}

RENAME_CANDIDATE_COLUMNS = (
    "old_code", "new_code", "title", "old_last_term", "new_first_term_code",
    "same_subject", "shared_instructors", "approved")

COURSE_INSTRUCTOR_COLUMNS = (
    "subject_course", "instructor_key", "instructor_name", "professor_slug",
    "name_key", "match_method", "terms_taught", "sections", "first_term_code",
    "last_term_code", "last_term_label", "recent_terms", "avg_enrollment",
    "was_primary", "campuses", "methods")
OFFERING_COLUMNS = (
    "subject_course", "subject", "course_title", "first_term_code",
    "last_term_code", "last_term_label", "terms_offered", "pattern",
    "fall_years", "spring_years", "summer_years", "pattern_window_years",
    "avg_sections_per_term", "avg_section_size", "median_section_size",
    "credit_hours", "instructor_count", "offered_now")

TEACHING_COLUMNS = ("professor_slug", "name_key", "term_desc", "term_codes",
                    "course_codes", "campuses", "match_method", "scraped_at")
UNMATCHED_COLUMNS = ("term_desc", "instructor_key", "instructor_name",
                     "course_codes", "reason",
                     "candidates", "scraped_at")


def single_term_desc(rows):
    """The one term_desc all `rows` must share, or raise.

    `rows[0]["term_desc"]` alone reads from an unordered SELECT: if
    banner_sections ever holds more than one season's rows at once (a stale
    prune that didn't run, a partial write, a race with load_banner_to_crdb),
    whichever row happens to come back first silently decides which season
    every professor's chip gets labelled with. Fail loudly instead of
    guessing.
    """
    descs = {r["term_desc"] for r in rows}
    if len(descs) != 1:
        raise ValueError(
            f"banner_sections holds {len(descs)} distinct term_desc values "
            f"{sorted(descs)} — expected exactly one; refusing to guess")
    return next(iter(descs))


def catalog_index(cur):
    """name_key -> [(slug, name_key)]. A list, so collisions stay visible."""
    cur.execute("SELECT slug, name_key FROM professors_catalog")
    index = {}
    for slug, name_key in cur.fetchall():
        if name_key:
            index.setdefault(name_key, []).append((slug, name_key))
    return index


def match_one(instructor_key, index):
    """(slug, name_key, method, candidates). slug is None when unmatched or
    ambiguous; candidates is the slugs rejected as ambiguous (empty otherwise).

    Order: exact key, then ALIAS_MAP (nicknames and name changes already
    curated for RMP), then BANNER_ALIASES (variants only NUBanner uses).
    Nothing looser. Exact wins over both, so a catalog row spelled the way
    Banner spells it is never passed over for a curated variant.

    This used to also try a single-letter-middle strip and a
    punctuation-insensitive strip. Measured on the real Fall 2026 load: 2,236
    of 2,237 matches were exact name_key, 1 was an alias, and zero came from
    either fallback — they bought nothing. Worse, the middle-initial strip is
    applied to the Banner key and looked up in the exact index, so its only
    possible effect is "Banner has a middle initial the catalog doesn't" —
    exactly the case where "Smith, John A" could be a different person from
    the catalog's sole "john smith", and the len(hits) > 1 ambiguity check
    can't see that because there's only one hit to see. It was the last
    fallback that could still fuse two distinct people onto one profile, so it
    was removed along with the punctuation pass it was measured alongside.

    `candidates` is returned here (rather than left for the caller to
    re-derive via `index.get(instructor_key)`) because the ambiguity can be
    found via ALIAS_MAP: the hits live at the aliased key, not at
    instructor_key itself, so re-looking-up instructor_key in the caller would
    come up empty and banner_unmatched.candidates would silently lose the very
    thing it exists to make reviewable.
    """
    for candidate_key, method in (
        (instructor_key, "name_key"),
        (ALIAS_MAP.get(instructor_key), "alias"),
        (BANNER_ALIASES.get(instructor_key), "banner_alias"),
    ):
        if not candidate_key:
            continue
        hits = index.get(candidate_key)
        if not hits:
            continue
        if len(hits) > 1:
            return None, None, "ambiguous", [s for s, _ in hits]
        slug, name_key = hits[0]
        return slug, name_key, method, []

    return None, None, "no_match", []


def group_instructors(rows):
    """banner_sections rows -> one entry per instructor who actually teaches.

    Individual Instruction is thesis/directed-study supervision — 1,346 of 6,699
    Spring 2025 sections. It stays in banner_sections and is filtered here, so an
    instructor with nothing but supervision produces no chip.
    """
    groups = {}
    for r in rows:
        if (r.get("schedule_type") or "").lower() in NON_TEACHING_SCHEDULE_TYPES:
            continue
        key = r.get("instructor_key")
        if not key:
            continue
        g = groups.setdefault(key, {
            "name": r.get("instructor_name"),
            "courses": set(), "campuses": set(), "terms": set(),
        })
        if r.get("subject_course"):
            g["courses"].add(r["subject_course"])
        if r.get("campus") and r["campus"].strip().lower() not in NON_PLACE_CAMPUSES:
            g["campuses"].add(r["campus"])
        if r.get("term_code"):
            g["terms"].add(r["term_code"])

    return {
        key: {"name": g["name"],
              "course_codes": sorted(g["courses"]),
              "campuses": sorted(g["campuses"]),
              "term_codes": sorted(g["terms"])}
        for key, g in groups.items() if g["courses"]
    }


def build_rows(groups, index, term_desc, scraped_at):
    """(teaching rows, unmatched rows) as insert-ready tuples.

    Two distinct Banner instructor_keys can match the same catalog row — the
    only way left after FIX 4 removed the fuzzy passes is two ALIAS_MAP
    entries resolving to one name_key — and would otherwise produce two
    tuples sharing the same (name_key, term_desc) primary key. execute_values
    + ON CONFLICT DO UPDATE cannot apply two updates to the same row in one
    statement; psycopg2 raises "cannot affect row a second time" and the
    whole matcher dies, so groups that match the same name_key are merged
    here (union of course codes/campuses/term codes) before any row is built.
    """
    merged = {}   # matched name_key -> merged entry
    unmatched = []
    for instructor_key, g in sorted(groups.items()):
        slug, name_key, method, candidates = match_one(instructor_key, index)
        if not slug:
            courses = ",".join(g["course_codes"])
            unmatched.append((term_desc, instructor_key, g["name"],
                              courses, method, ",".join(candidates), scraped_at))
            continue
        entry = merged.setdefault(name_key, {
            "slug": slug, "method": method,
            "courses": set(), "campuses": set(), "term_codes": set(),
        })
        entry["courses"].update(g["course_codes"])
        entry["campuses"].update(g["campuses"])
        entry["term_codes"].update(g["term_codes"])

    # "|"-joined: campus names contain commas ("Oakland, CA",
    # "Vancouver, Canada"), so a comma-joined column would corrupt them into
    # extra bogus campuses on read. Course/term codes never contain commas,
    # so they stay comma-joined.
    teaching = [
        (e["slug"], name_key, term_desc, ",".join(sorted(e["term_codes"])),
         ",".join(sorted(e["courses"])), "|".join(sorted(e["campuses"])),
         e["method"], scraped_at)
        for name_key, e in sorted(merged.items())
    ]
    return teaching, unmatched


def _placeholder(cur):
    """sqlite uses ?, psycopg2 uses %s. The tests run on sqlite."""
    return "?" if isinstance(cur, sqlite3.Cursor) else "%s"


def _insert(cur, table, columns, rows):
    if not rows:
        return 0
    if isinstance(cur, sqlite3.Cursor):
        cur.executemany(
            f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' * len(columns))})", rows)
    else:
        conflict = "(name_key, term_desc)" if table == "professor_teaching" \
                   else "(term_desc, instructor_key)"
        updates = ", ".join(f"{c} = excluded.{c}" for c in columns)
        execute_values(
            cur,
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s "
            f"ON CONFLICT {conflict} DO UPDATE SET {updates}",
            rows, page_size=2000)
    return len(rows)


def write_results(cur, term_desc, teaching, unmatched):
    """Replace this run's rows for `term_desc`, drop stale older seasons.

    A professor who leaves the current roster — cancelled section,
    reassignment, conversion to Individual Instruction, a catalog rename that
    breaks the match — has no row in `teaching`/`unmatched` this run. `_insert`
    is an upsert, so without deleting THIS season's existing rows first, their
    old row (and public chip) would survive untouched until the 21-day
    staleness guard expires it — three weeks of a false public claim, in the
    middle of add/drop. The caller (`main`) commits once after this returns,
    so the two deletes and two inserts for both tables share one transaction:
    a crash here cannot leave either table empty.
    """
    ph = _placeholder(cur)
    cur.execute(f"DELETE FROM professor_teaching WHERE term_desc <> {ph}", (term_desc,))
    cur.execute(f"DELETE FROM banner_unmatched WHERE term_desc <> {ph}", (term_desc,))
    cur.execute(f"DELETE FROM professor_teaching WHERE term_desc = {ph}", (term_desc,))
    cur.execute(f"DELETE FROM banner_unmatched WHERE term_desc = {ph}", (term_desc,))
    n_teaching = _insert(cur, "professor_teaching", TEACHING_COLUMNS, teaching)
    n_unmatched = _insert(cur, "banner_unmatched", UNMATCHED_COLUMNS, unmatched)
    return n_teaching, n_unmatched


def check_match_gate(groups, teaching, previous=None, dry_run=False):
    """Refuse to write when this looks like a broken run, not a quiet season.

    Extracted out of `main` so the gate is testable offline: `main` needs a
    live CRDB connection to reach this point, and the gate itself needs none.

    `previous` is how many professor_teaching rows the last run wrote (None
    on a first run). Two refusals:
      - nothing matched although Banner has instructors — an empty catalog
        index, whatever the history;
      - fewer than MIN_KEPT_RATIO of the previous run's matches — a partial
        or mismatched index (professors_catalog rebuilt mid-run, a name_key
        normalization change).

    `groups` empty is a different failure — "Banner legitimately has almost
    nobody" — and is already owned by the "banner_sections is empty" check
    earlier in `main`.

    dry_run=True never raises: --dry-run exists so an operator can see the
    numbers on a bad run, not have the tool die before printing them.
    """
    if dry_run or not groups:
        return
    if not teaching:
        raise MatchGateFailed(
            f"matched 0 of {len(groups)} instructors who teach this term. "
            f"Banner clearly has data, so an empty or mismatched "
            f"professors_catalog index is the likely cause. Refusing to write; "
            f"existing rows are untouched.")
    if previous and len(teaching) / previous < MIN_KEPT_RATIO:
        raise MatchGateFailed(
            f"matched {len(teaching)} instructors, but the previous run matched "
            f"{previous} — below the MIN_KEPT_RATIO of {MIN_KEPT_RATIO:.0%}. "
            f"A partial or mismatched professors_catalog index is the likely "
            f"cause. Refusing to write; existing rows are untouched.")


def current_season(term_rows):
    """banner_terms rows -> (label, [term codes]) for the chip, or raise.

    The same rule as banner_api.select_season, applied to what is stored
    rather than to a live getTerms call: earliest open Fall/Spring label wins,
    with every term code that shares it (Law and CPS run parallel codes).
    """
    seasons = {}
    for r in term_rows:
        if r["view_only"] or r["season_group"] not in ("Fall", "Spring"):
            continue
        seasons.setdefault(r["term_label"], []).append(str(r["term_code"]))
    if not seasons:
        raise ValueError("banner_terms has no open Fall/Spring term — run "
                         "load_banner_to_crdb.py first")
    chosen = min(seasons, key=lambda label: min(int(c) for c in seasons[label]))
    return chosen, sorted(seasons[chosen], key=int)


def approved_renames(offerings, course_renames=None, subject_renames=None):
    """[{"old_code", "new_code"}] for every approved pair whose codes exist."""
    course_renames = COURSE_RENAMES if course_renames is None else course_renames
    subject_renames = SUBJECT_RENAMES if subject_renames is None else subject_renames
    codes = {o["subject_course"] for o in offerings}
    pairs = dict(course_renames)
    for old_subj, new_subj in subject_renames.items():
        for code in codes:
            if code.startswith(old_subj) and code[len(old_subj):].isdigit():
                successor = new_subj + code[len(old_subj):]
                if successor in codes:
                    pairs.setdefault(code, successor)
    return [{"old_code": o, "new_code": n} for o, n in sorted(pairs.items())
            if o in codes and n in codes]


def write_history(cur, course_instructors, offerings, candidates=(), renames=()):
    """Replace the history tables wholesale, in the caller's transaction.

    Derived entirely from banner_sections, so a full rebuild is always correct
    and a partial one never is: a course that lost its last section must lose
    its row too.
    """
    approved = {(r["old_code"], r["new_code"]) for r in renames}
    candidates = [{**c, "approved": (c["old_code"], c["new_code"]) in approved}
                  for c in candidates]
    for table in ("banner_course_instructors", "banner_course_offerings",
                  "banner_course_rename_candidates", "banner_course_renames"):
        cur.execute(f"DELETE FROM {table}")
    as_rows = lambda dicts, cols: [tuple(d.get(c) for c in cols) for d in dicts]  # noqa: E731
    for table, cols, dicts in (
            ("banner_course_instructors", COURSE_INSTRUCTOR_COLUMNS, course_instructors),
            ("banner_course_offerings", OFFERING_COLUMNS, offerings),
            ("banner_course_rename_candidates", RENAME_CANDIDATE_COLUMNS, candidates),
            ("banner_course_renames", ("old_code", "new_code"), list(renames))):
        if not dicts:
            continue
        if isinstance(cur, sqlite3.Cursor):
            cur.executemany(
                f"INSERT INTO {table} ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' * len(cols))})", as_rows(dicts, cols))
        else:
            execute_values(cur, f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s",
                           as_rows(dicts, cols), page_size=2000)
    return len(course_instructors), len(offerings)


SECTION_SELECT = """
    SELECT s.term_code, s.crn, s.subject, s.subject_course, s.course_title,
           s.campus, s.instructional_method, s.schedule_type,
           s.credit_hours_low, s.credit_hours_high, s.enrollment,
           t.term_label, t.season_group, t.view_only
    FROM banner_sections s JOIN banner_terms t ON t.term_code = s.term_code
"""
SECTION_FIELDS = ("term_code", "crn", "subject", "subject_course", "course_title",
                  "campus", "instructional_method", "schedule_type",
                  "credit_hours_low", "credit_hours_high", "enrollment", "term_label",
                  "season_group", "closed")

INSTRUCTOR_SELECT = """
    SELECT i.term_code, i.crn, i.instructor_key, i.instructor_name,
           i.is_primary, s.subject_course, s.schedule_type,
           s.campus, s.instructional_method, s.enrollment,
           t.term_label, t.view_only
    FROM banner_section_instructors i
    JOIN banner_sections s ON s.term_code = i.term_code AND s.crn = i.crn
    JOIN banner_terms t ON t.term_code = i.term_code
"""
INSTRUCTOR_FIELDS = ("term_code", "crn", "instructor_key", "instructor_name",
                     "is_primary", "subject_course",
                     "schedule_type", "campus", "instructional_method",
                     "enrollment", "term_label", "closed")


def read_banner(cur):
    """(term rows, section rows, instructor rows) as dicts, from the three tables."""
    cur.execute("SELECT term_code, term_label, season_group, view_only FROM banner_terms")
    terms = [dict(zip(("term_code", "term_label", "season_group", "view_only"), r))
             for r in cur.fetchall()]
    cur.execute(SECTION_SELECT)
    sections = [dict(zip(SECTION_FIELDS, r)) for r in cur.fetchall()]
    cur.execute(INSTRUCTOR_SELECT)
    instructors = [dict(zip(INSTRUCTOR_FIELDS, r)) for r in cur.fetchall()]
    for r in sections + instructors:
        r["closed"] = bool(r["closed"])
    return terms, sections, instructors


def chip_rows(instructors, term_desc, codes):
    """The current season's instructor rows, shaped as group_instructors expects."""
    codes = set(codes)
    return [{**r, "term_desc": term_desc} for r in instructors if r["term_code"] in codes]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Match Banner instructors to the catalog")
    ap.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    ap.add_argument("--local-db", help="read and write a sqlite staging file instead of "
                                       "CockroachDB (no professors_catalog there, so "
                                       "nothing matches a profile)")
    args = ap.parse_args(argv)

    if args.local_db:
        open_conn = lambda: sqlite3.connect(args.local_db)  # noqa: E731
    else:
        dsn = os.environ.get("CRDB_DATABASE_URL")
        if not dsn:
            print("CRDB_DATABASE_URL is not set", file=sys.stderr)
            return 1
        open_conn = lambda: connect(dsn)  # noqa: E731

    conn = open_conn()
    cur = conn.cursor()
    for ddl in (TEACHING_DDL, UNMATCHED_DDL, HISTORY_DDL):
        for stmt in ddl.split(";"):
            if stmt.strip():
                cur.execute(stmt.replace("TIMESTAMPTZ", "TIMESTAMP") if args.local_db else stmt)
    conn.commit()

    term_rows, sections, instructors = read_banner(cur)
    if not sections:
        print("banner_sections is empty — run load_banner_to_crdb.py first",
              file=sys.stderr)
        return 1
    # A staging file has no catalog unless one was copied in (slug, name_key
    # from CockroachDB) to test profile links offline.
    local_catalog = bool(args.local_db) and cur.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'professors_catalog'").fetchone()
    if args.local_db and not local_catalog:
        index = {}
        print("local staging file: no professors_catalog, so every instructor is "
              "unmatched — history is built, profile links are not")
    else:
        index = catalog_index(cur)
    # The last run's matches, the baseline for the gate. Read before anything
    # is written, so it is always the previous run's count, never this one's.
    cur.execute("SELECT count(*) FROM professor_teaching")
    previous = cur.fetchone()[0]
    conn.close()

    # ── the current season's chip ──
    term_desc, codes = current_season(term_rows)
    rows = chip_rows(instructors, term_desc, codes)
    groups = group_instructors(rows)
    teaching, unmatched = build_rows(
        groups, index, term_desc, datetime.now(timezone.utc).isoformat())

    total = len(teaching) + len(unmatched)
    rate = len(teaching) / total * 100 if total else 0
    print(f"{term_desc}: {len(teaching)} matched ({rate:.0f}%), "
          f"{len(unmatched)} unmatched of {total} instructors")

    # Over-matching is the dangerous direction: it means the normalizer fused
    # distinct people and someone's profile now claims a course they don't teach.
    if rate > 85:
        print("WARNING: match rate above 85% — measured ~80% on 2026-08-04. "
              "Check for over-matching before trusting this.", file=sys.stderr)

    # Must run after the summary line above (an operator diagnosing a bad
    # --dry-run needs to see the numbers) and must precede any write.
    check_match_gate(groups, teaching, previous=previous,
                     dry_run=args.dry_run or (bool(args.local_db) and not local_catalog))

    # ── history across every stored term ──
    def match(key):
        slug, name_key, method, _ = match_one(key, index)
        return slug, name_key, method

    course_instructors = build_course_instructors(instructors, match)
    offerings = build_course_offerings(sections, instructors)
    candidates = rename_candidates(offerings, course_instructors)
    renames = approved_renames(offerings)
    print(f"renames: {len(candidates)} candidates to review, {len(renames)} approved")
    matched_pairs = sum(1 for r in course_instructors if r["professor_slug"])
    n_terms = len({s["term_code"] for s in sections})
    print(f"history: {len(offerings)} courses across {n_terms} term codes, "
          f"{len(course_instructors)} course-instructor pairs "
          f"({matched_pairs} linked to a profile)")
    if not offerings:
        raise MatchGateFailed("banner_sections has rows but no course offering "
                              "could be built — refusing to wipe the history tables")

    if args.dry_run:
        print("dry run — nothing written")
        return 0

    # One transaction for all four tables: a page reading the chip and the
    # history together never sees them from two different runs.
    def write(c):
        return (write_results(c, term_desc, teaching, unmatched),
                write_history(c, course_instructors, offerings, candidates, renames))

    (n_teaching, n_unmatched), (n_pairs, n_courses) = with_retry(open_conn, write)
    print(f"wrote {n_teaching} teaching rows, {n_unmatched} unmatched, "
          f"{n_pairs} course-instructor rows, {n_courses} course offerings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
