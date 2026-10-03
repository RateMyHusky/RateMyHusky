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

No fuzzy matching, and a name is not identity on its own: two different people
share names across five years of rosters. A name match is only credited when
the course's subject is one the professor's catalog department teaches (learned
from every other professor in that department), and never when a term's own
roster listed the name twice. A wrong match publishes a course on the wrong
person's profile, so ambiguity is recorded, never resolved.

Only Banner's own instructor rows (source = 'banner') are read. The one-off
import that filled Fall 2021 to Summer 2025 is not Banner data and stays out
of the public history until those terms are scraped from Banner.

Usage
-----
    python match_banner_instructors.py
"""

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

from psycopg2.extras import execute_values

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")))

from banner_api import pattern_season  # noqa: E402
from banner_history import (academic_year,  # noqa: E402
                            build_course_instructors, build_course_offerings,
                            is_teaching, place, rename_candidates)
from prof_aliases import ALIAS_MAP  # noqa: E402

# One definition of how to reach CRDB, shared with the loader: sslmode must
# override the DSN's verify-full or the connection fails outright, and the DNS
# flake is retried. with_retry comes from the same place so both write paths
# replay a 40001 identically.
from load_banner_to_crdb import apply_ddl, connect, with_retry  # noqa: E402

# A run must keep at least this share of the previous run's matches. Not a
# share of Banner: the catalog only holds professors with an RMP page, so most
# Banner instructors legitimately match nothing (36% matched on Fall 2026,
# measured 2026-10-02). A broken run — an empty or mismatched catalog index, a
# name_key normalization change — shows up as a collapse against last week.
MIN_KEPT_RATIO = 0.5

# A department needs at least this many professors matched by exact name before
# its subjects can vouch for anyone; below it there is too little to learn from,
# and the subject check abstains (see subject_agrees).
MIN_DEPARTMENT_PROFESSORS = 3
# Two subjects are related when at least this many different instructors taught
# both in the same term (MATH and CS, ENGL and HIST). Measured 2026-10-03 on the
# local Fall 2025 – Fall 2026 stage: CHEM and FINA share none.
MIN_RELATED_INSTRUCTORS = 2
# An unrelated subject only counts as a namesake's when it was taught at least
# this many academic years away from the professor's own teaching: a gap of a
# full year or more with nothing in between. Closer than that is the same
# person (measured 2026-10-03 on the local stage: every subject rejected at a
# smaller gap was a real professor's PJM, AAI or TELE course one term earlier).
MIN_NAMESAKE_GAP_YEARS = 2
# RMP leaves some departments blank or literally "unspecified".
_NO_DEPARTMENT = {"", "unspecified", "none"}
_SUBJECT_RE = re.compile(r"^[A-Za-z]+")

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


def catalog_index(cur):
    """name_key -> [(slug, name_key)]. A list, so collisions stay visible."""
    cur.execute("SELECT slug, name_key FROM professors_catalog")
    index = {}
    for slug, name_key in cur.fetchall():
        if name_key:
            index.setdefault(name_key, []).append((slug, name_key))
    return index


def catalog_departments(cur):
    """slug -> department, or None where the catalog has none."""
    cur.execute("SELECT slug, department FROM professors_catalog")
    out = {}
    for slug, dept in cur.fetchall():
        d = (dept or "").strip()
        out[slug] = None if d.lower() in _NO_DEPARTMENT else d
    return out


def subject_of(subject_course):
    """"CHEM1211" -> "CHEM"."""
    m = _SUBJECT_RE.match(subject_course or "")
    return m.group(0).upper() if m else None


def department_subjects(instructor_rows, index, departments):
    """{department: {subject: {slugs}}} from exact, unambiguous name matches.

    What a department teaches, learned from Banner itself: every professor whose
    Banner name equals exactly one catalog name_key contributes the subjects
    they teach to their catalog department. RMP departments ("Business",
    "Engineering") don't map one-to-one onto Banner subjects, so this is learned
    rather than hand-written.
    """
    out = {}
    for r in instructor_rows:
        if not is_teaching(r):
            continue
        hits = index.get(r.get("instructor_key")) or []
        subject = subject_of(r.get("subject_course"))
        if len(hits) != 1 or not subject:
            continue
        slug = hits[0][0]
        dept = departments.get(slug)
        if dept:
            out.setdefault(dept, {}).setdefault(subject, set()).add(slug)
    return out


def subject_agrees(department, subject, slug, stats):
    """True / False / None: is `subject` one `department` teaches?

    Judged by the *other* professors in the department, so a second person who
    shares the professor's name can't vouch for their own courses (the Wei Wang
    who teaches CHEM is not evidence that the Finance Wei Wang does). None means
    there is nothing to judge by: no department, or too few matched professors
    in it.
    """
    if not department or department not in stats:
        return None
    by_subject = stats[department]
    professors = set().union(*by_subject.values())
    if len(professors) < MIN_DEPARTMENT_PROFESSORS:
        return None
    return bool(by_subject.get(subject, set()) - {slug})


def related_subjects(teaching):
    """{subject: {subjects}} taught together in one term by enough instructors.

    `teaching` is subjects_by_term's output. Joint appointments and
    cross-listings make these pairs common between neighbouring fields and
    essentially absent between unrelated ones, which is what lets a professor's
    second subject pass without letting a namesake's pass.
    """
    pairs = {}
    for key, terms in teaching.items():
        for subjects in terms.values():
            for a in subjects:
                for b in subjects:
                    if a != b:
                        pairs.setdefault((a, b), set()).add(key)
    out = {}
    for (a, b), keys in pairs.items():
        if len(keys) >= MIN_RELATED_INSTRUCTORS:
            out.setdefault(a, set()).add(b)
    return out


def subjects_by_term(instructor_rows):
    """{instructor_key: {term_code: {subjects}}} over teaching rows."""
    out = {}
    for r in instructor_rows:
        subject = subject_of(r.get("subject_course"))
        if r.get("instructor_key") and subject and is_teaching(r):
            out.setdefault(r["instructor_key"], {}).setdefault(
                str(r["term_code"]), set()).add(subject)
    return out


class Identity:
    """Everything a match needs beyond the name: catalog departments, what each
    department teaches, every subject each name taught per term, and the names
    a term's roster listed more than once.

    Built once per run and called as identity(key, course, term_codes) for
    the history (banner_history's match contract), or through resolve() for
    the chip, which judges an instructor's whole course list at once.
    """

    def __init__(self, index, departments=None, subject_stats=None, roster_duplicates=(),
                 teaching=None):
        self.index = index
        self.departments = departments or {}
        self.stats = subject_stats or {}
        self.duplicates = set(roster_duplicates)
        self.teaching = teaching or {}
        self.related = related_subjects(self.teaching)
        self._personal = {}
        self._span = {}

    def active_span(self, key, slug):
        """(first, last) term code in which this name taught a subject that
        belongs to the professor, or None if it never did."""
        if (key, slug) not in self._span:
            terms = [int(t) for t, subjects in self.teaching.get(key, {}).items()
                     if any(self.verdict(key, slug, s) is True for s in subjects)]
            self._span[(key, slug)] = (min(terms), max(terms)) if terms else None
        return self._span[(key, slug)]

    def belongs(self, key, slug, method, subject, term_codes):
        """Is a course in `subject`, taught in `term_codes`, this professor's?

        An ALIAS_MAP match needs the subject to belong outright (verdict True).
        An exact name is refused only on evidence of a second person: the
        subject belongs to nothing the professor or their department teaches,
        *and* it was taught at least MIN_NAMESAKE_GAP_YEARS academic years
        away from every term in which the name taught the professor's own
        subjects. Two namesakes active in the same years would share a term,
        which the roster check refuses; one who slipped past it taught well
        before or after the professor did (the reviewer's case: CHEM1211 in
        2022, FINA2201 in 2026). A professor's cross-department course near
        their own teaching years is kept, as is everything for a name with no
        subject the department vouches for (RMP's department labels are too
        coarse to overrule Banner there).
        """
        v = self.verdict(key, slug, subject)
        if method == "alias":
            return v is True
        if v is not False:
            return True
        span = self.active_span(key, slug)
        if span is None or not term_codes:
            return True
        first, last = academic_year(span[0]), academic_year(span[1])
        return any(first - MIN_NAMESAKE_GAP_YEARS < academic_year(t) < last + MIN_NAMESAKE_GAP_YEARS
                   for t in term_codes)

    def personal_subjects(self, key, slug):
        """Subjects this name taught in a term where it also taught one the
        department vouches for.

        Within one term a name is one person (two people sharing it there show
        up as a roster duplicate and are refused), so a professor's cross-listed
        or interdisciplinary courses (an English professor's HIST section, a
        chemical engineer's ENLR one) ride on the department subject taught
        alongside them. A namesake who never shares a term with the professor
        (the CHEM Wei Wang of 2022, the FINA one of 2026) gets no such anchor.
        """
        if (key, slug) not in self._personal:
            dept = self.departments.get(slug)
            personal = set()
            for subjects in self.teaching.get(key, {}).values():
                if any(subject_agrees(dept, s, slug, self.stats) is True for s in subjects):
                    personal |= subjects
            self._personal[(key, slug)] = personal
        return self._personal[(key, slug)]

    def verdict(self, key, slug, subject):
        """True / False / None: does `subject` belong to this professor?

        True when the department teaches it (subject_agrees), when the name
        taught it alongside a department subject in one term
        (personal_subjects), or when it is related to a subject the department
        teaches (related_subjects). None when the department has too little
        evidence to judge; False otherwise.
        """
        dept = self.departments.get(slug)
        agrees = subject_agrees(dept, subject, slug, self.stats)
        if agrees is None:
            return None
        if agrees or subject in self.personal_subjects(key, slug):
            return True
        taught = {s for s in self.stats[dept] if subject_agrees(dept, s, slug, self.stats)}
        return bool(self.related.get(subject, set()) & taught)

    def resolve(self, key, courses, term_codes=()):
        """(slug, name_key, method, candidates, kept_courses).

        A name a term's roster listed twice is refused outright: it may be two
        people, and nothing here can tell which one taught what. Otherwise the
        name is resolved (match_one), and each course is kept only if its
        subject agrees with the professor's department:
          - BANNER_ALIASES entries were each checked by hand, so they pass;
          - an exact name passes where the check abstains (None) and fails
            where it says no;
          - an ALIAS_MAP entry needs a yes. Those aliases were chosen for
            particular RMP listings, not for every Banner legal name.
        No course left means no match.
        """
        if any((t, key) in self.duplicates for t in term_codes):
            return None, None, "roster_duplicate", [], []
        slug, name_key, method, candidates = match_one(key, self.index)
        if not slug:
            return None, None, method, candidates, []
        if method == "banner_alias":
            return slug, name_key, method, [], list(courses)
        kept = [c for c in courses
                if self.belongs(key, slug, method, subject_of(c), term_codes)]
        if not kept:
            judged = [self.verdict(key, slug, subject_of(c)) for c in courses]
            reason = "subject_mismatch" if False in judged else "alias_unverified"
            return None, None, reason, [slug], []
        return slug, name_key, method, [], kept

    def __call__(self, key, course=None, term_codes=()):
        slug, name_key, method, _, _ = self.resolve(key, [course] if course else [], term_codes)
        return slug, name_key, method


def match_one(instructor_key, index):
    """Name resolution only: (slug, name_key, method, candidates). slug is None
    when unmatched or ambiguous; candidates is the slugs rejected as ambiguous
    (empty otherwise). Identity.resolve adds the subject and roster checks; call
    that, not this, to decide what a profile shows.

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
        if not is_teaching(r):
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
        if place(r.get("campus")):
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


def build_rows(groups, identity, term_desc, scraped_at):
    """(teaching rows, unmatched rows) as insert-ready tuples.

    `identity` is an Identity, or a bare catalog index (an Identity with no
    departments, so only exact names match). A matched instructor's chip lists
    only the courses whose subject agrees with their department.

    Two distinct Banner instructor_keys can match the same catalog row — the
    only way left after FIX 4 removed the fuzzy passes is two ALIAS_MAP
    entries resolving to one name_key — and would otherwise produce two
    tuples sharing the same (name_key, term_desc) primary key. execute_values
    + ON CONFLICT DO UPDATE cannot apply two updates to the same row in one
    statement; psycopg2 raises "cannot affect row a second time" and the
    whole matcher dies, so groups that match the same name_key are merged
    here (union of course codes/campuses/term codes) before any row is built.
    """
    if not isinstance(identity, Identity):
        identity = Identity(identity)
    merged = {}   # matched name_key -> merged entry
    unmatched = []
    for instructor_key, g in sorted(groups.items()):
        slug, name_key, method, candidates, kept = identity.resolve(
            instructor_key, g["course_codes"], g["term_codes"])
        if not slug:
            courses = ",".join(g["course_codes"])
            unmatched.append((term_desc, instructor_key, g["name"],
                              courses, method, ",".join(candidates), scraped_at))
            continue
        entry = merged.setdefault(name_key, {
            "slug": slug, "method": method,
            "courses": set(), "campuses": set(), "term_codes": set(),
        })
        entry["courses"].update(kept)
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


def _insert(cur, table, columns, rows):
    """Plain insert: write_results has already emptied the table."""
    if not rows:
        return 0
    if isinstance(cur, sqlite3.Cursor):
        cur.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' * len(columns))})", rows)
    else:
        execute_values(
            cur, f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s",
            rows, page_size=2000)
    return len(rows)


def write_results(cur, term_desc, teaching, unmatched):
    """Replace both tables with this run's rows for `term_desc`.

    Every row goes, this season's included: a professor who left the current
    roster (cancelled section, reassignment, conversion to Individual
    Instruction, a catalog rename that breaks the match) has no row this run,
    and keeping their old one would leave a false public chip until the
    21-day staleness guard expired it. The caller commits once after this
    returns, so the deletes and inserts share one transaction: a crash here
    cannot leave either table empty.
    """
    cur.execute("DELETE FROM professor_teaching")
    cur.execute("DELETE FROM banner_unmatched")
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
    rather than to a live getTerms call: earliest open Fall/Spring season wins,
    with every term code that shares it (Law and CPS run parallel codes). A CPS
    Winter quarter belongs to the Spring of its year (banner_api.pattern_season),
    so its instructors get the chip alongside the Spring semester's.
    """
    seasons = {}
    for r in term_rows:
        season = pattern_season(r["season_group"])
        if r["view_only"] or season not in ("Fall", "Spring"):
            continue
        label = f"{season} {str(r['term_label']).split()[-1]}"
        seasons.setdefault(label, []).append(str(r["term_code"]))
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


# "closed" is scraped_closed, not view_only: sync_view_only flips view_only
# before a term's final re-scrape, so between the two the stored enrollment is
# still a mid-registration snapshot and must not feed class sizes or count the
# year as complete.
SECTION_SELECT = """
    SELECT s.term_code, s.crn, s.subject, s.subject_course, s.course_title,
           s.campus, s.instructional_method, s.schedule_type,
           s.credit_hours_low, s.credit_hours_high, s.enrollment,
           t.term_label, t.season_group, t.scraped_closed
    FROM banner_sections s JOIN banner_terms t ON t.term_code = s.term_code
"""
SECTION_FIELDS = ("term_code", "crn", "subject", "subject_course", "course_title",
                  "campus", "instructional_method", "schedule_type",
                  "credit_hours_low", "credit_hours_high", "enrollment", "term_label",
                  "season_group", "closed")

# Banner's own rows only; see the module docstring on the one-off import.
INSTRUCTOR_SELECT = """
    SELECT i.term_code, i.crn, i.instructor_key, i.instructor_name,
           i.is_primary, s.subject_course, s.schedule_type,
           s.campus, s.instructional_method, s.enrollment,
           t.term_label, t.scraped_closed
    FROM banner_section_instructors i
    JOIN banner_sections s ON s.term_code = i.term_code AND s.crn = i.crn
    JOIN banner_terms t ON t.term_code = i.term_code
    WHERE i.source = 'banner'
"""
INSTRUCTOR_FIELDS = ("term_code", "crn", "instructor_key", "instructor_name",
                     "is_primary", "subject_course",
                     "schedule_type", "campus", "instructional_method",
                     "enrollment", "term_label", "closed")


TERM_FIELDS = ("term_code", "term_label", "season_group", "view_only", "scraped_at")


def read_banner(cur):
    """(term rows, section rows, instructor rows) as dicts, from the three tables."""
    cur.execute(f"SELECT {', '.join(TERM_FIELDS)} FROM banner_terms")
    terms = [dict(zip(TERM_FIELDS, r)) for r in cur.fetchall()]
    cur.execute(SECTION_SELECT)
    sections = [dict(zip(SECTION_FIELDS, r)) for r in cur.fetchall()]
    cur.execute(INSTRUCTOR_SELECT)
    instructors = [dict(zip(INSTRUCTOR_FIELDS, r)) for r in cur.fetchall()]
    for r in sections + instructors:
        r["closed"] = bool(r["closed"])
    return terms, sections, instructors


def read_roster_duplicates(cur):
    """{(term_code, instructor_key)} a term's roster listed more than once."""
    cur.execute("SELECT term_code, instructor_key FROM banner_roster_duplicates")
    return {(str(t), k) for t, k in cur.fetchall()}


def chip_scraped_at(term_rows, codes):
    """When the chip's terms were last scraped: the oldest of them.

    professor_teaching.scraped_at drives the 21-day staleness guard in
    backend/teaching_history.py. Stamping it with the matcher's own clock
    would let a matcher that now runs every week hide a chip term whose scrape
    has been failing for a month.
    """
    def as_utc(stamp):
        # CockroachDB hands back datetimes; sqlite, "YYYY-MM-DD HH:MM:SS" text in UTC.
        dt = stamp if isinstance(stamp, datetime) else datetime.fromisoformat(str(stamp))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    codes = set(codes)
    stamps = [as_utc(r["scraped_at"]) for r in term_rows
              if str(r["term_code"]) in codes and r.get("scraped_at")]
    return min(stamps).isoformat() if stamps else datetime.now(timezone.utc).isoformat()


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
    apply_ddl(cur)    # the loader's tables, so a stage file from before a new one still reads
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
        index, departments = {}, {}
        print("local staging file: no professors_catalog, so every instructor is "
              "unmatched — history is built, profile links are not")
    else:
        index = catalog_index(cur)
        departments = catalog_departments(cur)
    identity = Identity(index, departments,
                        department_subjects(instructors, index, departments),
                        read_roster_duplicates(cur), subjects_by_term(instructors))
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
        groups, identity, term_desc, chip_scraped_at(term_rows, codes))

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
    course_instructors = build_course_instructors(instructors, identity)
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
