"""Scrape NUBanner terms, gated so a bad term writes nothing.

Every gate here guards a silent failure. Banner's sticky filters mean a broken
resetDataForm returns the *previous* query's rows with a 200 and no error, so
"looks like it worked" is not evidence.

Two kinds of term, scraped on two schedules:

  open       Not yet marked "(View Only)": the current term, plus the next one
             once registration opens. Rosters and enrollment move until add/drop
             ends, so these are re-scraped every run.
  closed     "(View Only)". Frozen — Banner keeps every section, instructor and
             final headcount back to Fall 2009. Scraped once, then never again,
             except for one final pass on a term that was last seen open (its
             enrollment was a mid-registration snapshot).

`plan_terms` decides which codes a run touches; `scrape_term` scrapes one.

Usage
-----
    python banner_scrape.py                  # open terms, report only
    python banner_scrape.py --term 202710    # one term code
    python banner_scrape.py --json-out x.json
"""

import argparse
import json
import sys
from datetime import date

from banner_api import (NON_TEACHING_SCHEDULE_TYPES, ROSTER_REQUEST_CAP,
                        parse_section, parse_term, section_end_dates,
                        select_season)
from banner_client import BannerClient

MIN_SECTION_RATIO = 0.8          # >20% drop vs the last scrape of this term aborts
MAX_FACULTY_FAILURE_RATIO = 0.02  # >2% unresolvable CRNs aborts
MIN_ROSTER_RATIO = 0.5           # distinct instructors vs get_instructor
MIN_FACULTY_FAILURES_TOLERATED = 3  # a handful of transient lookup failures shouldn't abort the run
# ROSTER_REQUEST_CAP lives in banner_api.py, shared with banner_client's
# instructor_roster request — see the comment there for why the two must
# never drift apart.

# Backfill floor, as a term code: Fall 2021 (202210), Northeastern's first
# normal in-person term after NUflex. Measured 2026-10-01: 39% of Fall 2026's
# instructors were already teaching in Fall 2021, and 46% of the site's RMP
# reviews are from 2021 on. Fall 2020 and Spring 2021 are excluded on purpose —
# their formats and class sizes would skew every "usually" on the site.
DEFAULT_SINCE_TERM = "202210"

# Terms before this code are scraped sections-only: their instructor rows came
# from a one-off import (source 'import' in prod), which Banner confirmed at
# 98-99% for CS and PSYC in Fall 2022 and Fall 2024. That import's Fall 2025 is
# incomplete (59% of Banner's sections against the usual 68-70%), so Banner owns
# instructors from Fall 2025 on. The import is not Banner data, so the matcher
# leaves it out of the public history; lowering this re-scrapes those terms'
# instructors from Banner (~7,000 requests a term) and brings them in.
DEFAULT_INSTRUCTORS_FROM = "202610"


class SanityGateFailed(RuntimeError):
    """A gate refused the term. Nothing has been written for it."""


def plan_terms(terms, known, mode, since_term=DEFAULT_SINCE_TERM):
    """getTerms rows -> [(term_code, parsed term)] this run should scrape.

    `known` is {term_code: closed_when_last_scraped} from banner_terms.

    mode "current": every open term. Re-scraped each run, because rosters,
    reassignments and enrollment all move until the term closes. A term whose
    last meeting has passed is scraped once more as closed (see scrape_term)
    and then skipped here, even while Banner is slow to mark it View Only.

    mode "backfill": closed terms from `since_term` on that are either missing
    or were last scraped while still open. Newest first, so an interrupted
    backfill has already covered the terms students are likeliest to ask about.

    Rows getTerms can't parse (a renamed season, a malformed row) are skipped
    rather than guessed at.
    """
    picked = []
    for t in terms:
        code = t.get("code")
        parsed = parse_term(t.get("description"))
        if code is None or parsed is None:
            continue
        code = str(code)
        if mode == "current":
            if not parsed["view_only"] and known.get(code) is not True:
                picked.append((code, parsed))
        elif mode == "backfill":
            if not parsed["view_only"] or int(code) < int(since_term):
                continue
            if known.get(code) is True:     # already scraped after it closed
                continue
            picked.append((code, parsed))
        else:
            raise ValueError(f"unknown mode {mode!r}")
    return sorted(picked, key=lambda p: int(p[0]), reverse=True)


def _fetch_faculty(client, term_code, crns):
    """{crn: faculty-or-None}, with one sequential retry of the failures.

    The concurrent pass is where transient 5xx/timeouts land; a second, quieter
    pass recovers most of them, which matters more than it used to because the
    term is now replaced wholesale — a lookup that stays failed drops that
    section's instructors until the next run.
    """
    fetched = client.faculty_for_many(term_code, crns) if crns else {}
    for crn in [c for c in crns if fetched.get(c) is None]:
        fetched[crn] = client.faculty_for(term_code, crn)
    return fetched


def scrape_term(client, term_code, previous_count=None, today=None,
                view_only=False, with_instructors=True):
    """One term code -> {"sections": [...], "instructors": [...], "stats": {...}}.

    Every section is kept, including TBA ones: class size and "when is this
    offered" are properties of the section, not of whoever teaches it. Only the
    instructor rows need an attributable person.

    with_instructors=False stops after the section pages — ~15 requests for a
    whole term instead of ~7,000 — and returns instructors=None, which tells
    write_term to leave that term's instructor rows alone.

    The result's "ended" is True when an open term's last meeting has already
    passed: its enrollment is final, so the caller stores it as closed.
    "failed_crns" are the teaching sections whose faculty lookup failed even
    after the retry pass; write_term keeps their previous instructor rows.
    """
    today = today or date.today()

    raw_rows = list(client.iter_sections(term_code))
    if not raw_rows:
        raise SanityGateFailed(f"{term_code}: 0 sections returned")

    # Every row names its own term. A stale session (a bootstrap or reset that
    # silently kept the previous term) serves another term's rows with a 200,
    # and write_term would file them under this code.
    foreign = sorted({str(r["term"]) for r in raw_rows
                      if r.get("term") is not None and str(r["term"]) != str(term_code)})
    if foreign:
        raise SanityGateFailed(
            f"{term_code}: Banner returned rows for term(s) {', '.join(foreign)} — "
            f"the session is serving another term's search")

    # Banner marks closed terms "(View Only)", but has been slow to flip ended
    # summer terms (seen open on 2026-08-04 after their last meeting). Past its
    # last meeting a term's enrollment is final, so it is scraped as closed
    # rather than refused every week until Banner catches up.
    ended = False
    if not view_only:
        end_dates = section_end_dates(raw_rows)
        if end_dates and max(end_dates) < today:
            ended = True
            print(f"{term_code}: last meeting was {max(end_dates)} but Banner has "
                  f"not marked it View Only; storing this scrape as closed")

    sections = {}
    for raw in raw_rows:
        parsed = parse_section(raw)
        if parsed["crn"]:
            sections[parsed["crn"]] = parsed

    # previous_count is banner_terms.section_count from the last scrape of
    # this same term: every section, TBA included, so it is the same unit as
    # len(sections). A pagination truncation shows up here.
    if previous_count and len(sections) < previous_count * MIN_SECTION_RATIO:
        raise SanityGateFailed(
            f"{term_code}: section count dropped from {previous_count} (last "
            f"scrape) to {len(sections)} "
            f"(>{int((1 - MIN_SECTION_RATIO) * 100)}%) — refusing to overwrite")

    if not with_instructors:
        return {"sections": list(sections.values()), "instructors": None,
                "ended": ended, "failed_crns": [], "roster_duplicates": [],
                "stats": {"section_count": len(sections),
                          "attributed_sections": 0, "instructor_count": 0}}

    # No cache: every CRN is fetched every time a term is scraped. A cached CRN
    # can silently outlive an instructor reassignment (Banner moves a section
    # from Prof A to Prof B, or to TBA), which publishes someone else's course
    # under a real person's name. Closed terms are only scraped once anyway.
    # Non-teaching sections are never looked up — see NON_TEACHING_SCHEDULE_TYPES.
    to_fetch = [crn for crn, s in sections.items()
                if (s.get("schedule_type") or "").lower() not in NON_TEACHING_SCHEDULE_TYPES]
    fetched = _fetch_faculty(client, term_code, to_fetch)

    failures = sum(1 for crn in to_fetch if fetched.get(crn) is None)
    if failures > max(MIN_FACULTY_FAILURES_TOLERATED,
                      len(to_fetch) * MAX_FACULTY_FAILURE_RATIO):
        raise SanityGateFailed(
            f"{term_code}: {failures} of {len(to_fetch)} faculty lookups failed "
            f"(>{MAX_FACULTY_FAILURE_RATIO:.0%} of the batch)")

    instructors = []
    tba = 0        # [] — Banner assigned nobody
    unknown = 0    # None — the lookup itself failed
    for crn in to_fetch:
        faculty = fetched.get(crn)
        if faculty is None:
            unknown += 1
            continue
        if not faculty:
            tba += 1
            continue
        for person in faculty:
            instructors.append({"term_code": term_code, "crn": crn, **person})

    # Measured on the real Fall 2026 load: 1,134 of 9,505 (11.9%) sections had
    # nobody assigned, concentrated in studio/clinical subjects (DANC 100%,
    # THTR 84%, NRSG 53%). Printed unconditionally and before the gates below,
    # so the number is diffable between runs even when a gate then fires.
    print(f"{term_code}: {tba + unknown} of {len(to_fetch)} teaching sections "
          f"unattributed ({tba} TBA, {unknown} lookup failures); "
          f"{len(sections) - len(to_fetch)} non-teaching sections not looked up")

    if not instructors:
        raise SanityGateFailed(
            f"{term_code}: no instructor could be attributed to any of the "
            f"{len(to_fetch)} teaching sections — the faculty response shape has "
            f"probably changed")

    # instructor_roster returns None on transport failure, distinct from a
    # legitimately empty set — the roster check is the only independent
    # verification that pagination and resetDataForm worked.
    roster = client.instructor_roster(term_code)
    if roster is None:
        raise SanityGateFailed(
            f"{term_code}: instructor roster request failed — the only "
            f"independent check on pagination and resetDataForm could not run")

    # ROSTER_REQUEST_CAP is a request cap, not a real limit. Compared against
    # row_count, not len(keys): the cap applies to rows, and two rows
    # normalizing to one key would hide a truncation from a set-size check.
    if roster.row_count >= ROSTER_REQUEST_CAP:
        raise SanityGateFailed(
            f"{term_code}: roster returned {roster.row_count} rows, at or "
            f"above the max={ROSTER_REQUEST_CAP} request cap — the roster was "
            f"truncated and cannot be compared")

    found = {r["instructor_key"] for r in instructors}
    if roster.keys:
        if len(found) < len(roster.keys) * MIN_ROSTER_RATIO:
            raise SanityGateFailed(
                f"{term_code}: found {len(found)} instructors but the roster "
                f"lists {len(roster.keys)} — pagination or resetDataForm is broken")
        print(f"{term_code}: found {len(found)} instructors, roster lists "
              f"{len(roster.keys)}")

    return {
        "sections": list(sections.values()),
        "instructors": instructors,
        "ended": ended,
        "failed_crns": sorted(crn for crn in to_fetch if fetched.get(crn) is None),
        # Two roster rows that normalize to one name may be two people. Stored,
        # so the matcher can refuse to credit that name to a profile.
        "roster_duplicates": sorted(roster.duplicate_keys),
        "stats": {"section_count": len(sections),
                  "attributed_sections": len({r["crn"] for r in instructors}),
                  "instructor_count": len(found)},
    }


def scrape_season(client, previous_counts=None, today=None):
    """(display term, {term_code: scrape}) for the upcoming Fall/Spring season.

    Kept for --term-less dry runs of what the teaching chip will say. Every term
    code of the season is included: Law and CPS run on parallel term rows, and
    taking only the plain Semester row would omit every Law and CPS professor.
    """
    previous_counts = previous_counts or {}
    term_desc, term_codes = select_season(client.get_terms())
    out = {}
    for code in term_codes:
        client.bootstrap(code)   # per-term session cookie; required before searching
        out[code] = scrape_term(client, code,
                                previous_count=previous_counts.get(code),
                                today=today)
    return term_desc, out


def _teaching(instructors, sections):
    by_crn = {s["crn"]: s for s in sections}
    return [r for r in instructors
            if (by_crn.get(r["crn"], {}).get("schedule_type") or "").lower()
            not in NON_TEACHING_SCHEDULE_TYPES]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scrape NUBanner terms (no database)")
    ap.add_argument("--term", help="scrape one term code instead of the open season")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--json-out", help="write scraped rows to this path")
    args = ap.parse_args(argv)

    client = BannerClient()
    if args.term:
        terms = {str(t.get("code")): t for t in client.get_terms()}
        parsed = parse_term((terms.get(args.term) or {}).get("description")) or {}
        client.bootstrap(args.term)
        scrapes = {args.term: scrape_term(client, args.term,
                                          view_only=bool(parsed.get("view_only")))}
        term_desc = parsed.get("label") or args.term
    else:
        term_desc, scrapes = scrape_season(client)

    for code, s in scrapes.items():
        teaching = _teaching(s["instructors"] or [], s["sections"])
        print(f"{term_desc} [{code}]: {len(s['sections'])} sections, "
              f"{len(s['instructors'] or [])} instructor rows, "
              f"{len({r['instructor_key'] for r in teaching})} distinct teaching instructors")

    # This script never touches the database — the loader does — so --json-out
    # is the only write it can make, and it is what --dry-run has to gate.
    if args.json_out:
        if args.dry_run:
            print(f"dry run — not writing {args.json_out}")
        else:
            with open(args.json_out, "w") as f:
                json.dump({"term_desc": term_desc, "terms": scrapes}, f)
            print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
