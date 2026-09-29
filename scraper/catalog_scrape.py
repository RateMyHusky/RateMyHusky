"""Sweep catalog.northeastern.edu, gated so a bad run writes nothing.

232 static pages, no auth, no session state — the cheapest source in the
pipeline. That cheapness is also the risk: nothing here can fail loudly on its
own. A renamed slug, a truncated index or a CMS redesign all answer 200 and
simply yield fewer courses, and a run that replaces 5,199 rows with 400 reads
as a success everywhere except the row count. Every gate below turns one of
those into a refusal.

Writes JSON and nothing else — this module imports no database driver, so it
cannot reach CRDB even by accident. Loading is a separate step, the same split
banner_scrape.py uses.

Usage
-----
    python catalog_scrape.py --json-out catalog.json
    python catalog_scrape.py --json-out out.json --previous-count 5199
    python catalog_scrape.py --subject cs --json-out one.json   # dev: skip the gates
"""

import argparse
import json
import sys
import time
from datetime import date

import requests

from catalog_api import (BASE, INDEX_PATH, TIMEOUT, USER_AGENT, CatalogParseError,
                         PageNotFound, parse_courses, parse_subject_index)

MIN_SUBJECTS = 180              # 232 live on 2026-08-13; a fifth could retire before this is wrong
MAX_NOT_FOUND_RATIO = 0.1       # slugs in the index that 404 as pages — index/page disagreement
MIN_COURSE_RATIO = 0.9          # >10% fewer courses than the last run aborts, per docs/course-data-scope.md
REQUEST_DELAY = 0.25            # ~1 request every 250ms; the whole sweep is ~1 minute
RETRY_STATUSES = (429, 500, 502, 503, 504)
TRANSPORT_ERRORS = (requests.ConnectionError, requests.Timeout,
                    requests.exceptions.ChunkedEncodingError)
MAX_ATTEMPTS = 3


class SanityGateFailed(RuntimeError):
    """A gate refused the run. Nothing has been written."""


class CatalogResult:
    def __init__(self, courses, subjects, not_found, duplicate_codes):
        self.courses = courses
        self.subjects = subjects
        self.not_found = not_found
        self.duplicate_codes = duplicate_codes

    def to_json(self, today=None):
        return {
            "scraped_at": (today or date.today()).isoformat(),
            "source": BASE + INDEX_PATH,
            "subject_count": len(self.subjects),
            "course_count": len(self.courses),
            "subjects_not_found": self.not_found,
            "duplicate_codes": self.duplicate_codes,
            "subjects": [s._asdict() for s in self.subjects],
            "courses": [c._asdict() for c in self.courses],
        }


class CatalogClient:
    """One session, sequential, deliberately slow.

    No concurrency: the sweep is ~232 requests and finishes inside a minute
    serially, which is not worth the risk of looking like a scraper to a host
    that has never rate-limited us.
    """

    def __init__(self, session=None, sleep=time.sleep, delay=REQUEST_DELAY):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._sleep = sleep
        self._delay = delay

    def _get(self, path):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self.session.get(BASE + path, timeout=TIMEOUT)
            except TRANSPORT_ERRORS:
                # Measured 2026-08-13: the host drops the keep-alive connection
                # partway through a sequential sweep (RemoteDisconnected). A
                # status-only retry policy turns that into a failed run, so the
                # connection layer needs the same treatment — the next attempt
                # opens a fresh one.
                if attempt == MAX_ATTEMPTS:
                    raise
                self._sleep(attempt * 2)
                continue

            if response.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
                self._sleep(attempt * 2)
                continue
            response.raise_for_status()
            self._sleep(self._delay)
            return response.text
        raise RuntimeError(f"{path}: exhausted {MAX_ATTEMPTS} attempts")

    def index(self):
        return self._get(INDEX_PATH)

    def subject_page(self, slug):
        return self._get(f"/course-descriptions/{slug}/")


def scrape_catalog(client, previous_count=None, verbose=False):
    """The whole catalog, or an exception. Never a partial answer."""
    subjects = parse_subject_index(client.index())
    if len(subjects) < MIN_SUBJECTS:
        raise SanityGateFailed(
            f"index yielded {len(subjects)} subject pages, expected at least {MIN_SUBJECTS}")

    courses, not_found, duplicate_codes = [], [], []
    seen = {}

    for subject in subjects:
        try:
            page = client.subject_page(subject.slug)
        except PageNotFound:
            # Tolerated individually: a slug retired mid-edition still appears
            # in the index for a while. Gated in aggregate below.
            not_found.append(subject.slug)
            continue

        for course in parse_courses(page, subject.slug):
            if course.code in seen:
                # Cross-listed, or the same code under a second subject page.
                # First listing wins; the collision is reported rather than
                # silently resolved, because a sudden pile of these is what a
                # broken title regex looks like.
                duplicate_codes.append(course.code)
                continue
            seen[course.code] = course
            courses.append(course)

        if verbose:
            print(f"  {subject.slug:8s} {subject.subject:6s} {len(courses):5d} courses so far")

    not_found_ratio = len(not_found) / len(subjects)
    if not_found_ratio > MAX_NOT_FOUND_RATIO:
        raise SanityGateFailed(
            f"{len(not_found)} of {len(subjects)} subject pages not found "
            f"({not_found_ratio:.0%}) — the index and the pages disagree")

    if previous_count and len(courses) < previous_count * MIN_COURSE_RATIO:
        raise SanityGateFailed(
            f"{len(courses)} courses vs {previous_count} on the previous run "
            f"({len(courses) / previous_count:.0%}) — below the {MIN_COURSE_RATIO:.0%} floor")

    return CatalogResult(courses, subjects, not_found, duplicate_codes)


def scrape_one_subject(client, slug):
    """Dev path: one page, no gates, so a parser change is a two-second loop."""
    courses = parse_courses(client.subject_page(slug), slug)
    return CatalogResult(courses, [], [], [])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--json-out", required=True, help="where to write the scrape")
    parser.add_argument("--previous-count", type=int,
                        help="course count from the last run; enables the drop gate")
    parser.add_argument("--subject", help="scrape one subject slug and skip the gates")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    client = CatalogClient()
    started = time.time()

    try:
        if args.subject:
            result = scrape_one_subject(client, args.subject)
        else:
            result = scrape_catalog(client, args.previous_count, verbose=not args.quiet)
    except SanityGateFailed as gate:
        print(f"ABORTED: {gate}", file=sys.stderr)
        print("Nothing was written.", file=sys.stderr)
        return 1
    except (PageNotFound, CatalogParseError) as broken:
        print(f"ABORTED: {broken}", file=sys.stderr)
        return 1

    with open(args.json_out, "w", encoding="utf-8") as fh:
        json.dump(result.to_json(), fh, indent=2, ensure_ascii=False)

    elapsed = time.time() - started
    print(f"{len(result.courses)} courses from {len(result.subjects)} subjects "
          f"in {elapsed:.0f}s -> {args.json_out}")
    if result.not_found:
        print(f"  {len(result.not_found)} subject pages not found: {', '.join(result.not_found)}")
    if result.duplicate_codes:
        print(f"  {len(result.duplicate_codes)} duplicate codes, first listing kept")
    with_nupath = sum(1 for c in result.courses if c.nupath)
    print(f"  {with_nupath} courses carry an NUpath attribute")
    return 0


if __name__ == "__main__":
    sys.exit(main())
