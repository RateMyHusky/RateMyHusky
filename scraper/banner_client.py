"""NUBanner HTTP transport.

One shared Session for everything. Measured 2026-08-04: four separate
bootstrapped sessions ran at 0.83x the shared-session rate with identical p50,
so the ceiling is server capacity and extra sessions only add bootstrap cost.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

import requests

from banner_api import (BASE, CONCURRENCY, MAX_PAGES, PAGE_SIZE,
                        ROSTER_REQUEST_CAP, TIMEOUT, USER_AGENT,
                        normalize_instructor_key, parse_faculty)

RETRY_STATUSES = (500, 502, 503, 504)
MAX_ATTEMPTS = 3
HARD_STOP_STATUSES = (403, 429)


class BannerRateLimited(RuntimeError):
    """A 429 or 403. Never retried — quit and re-probe instead."""


class Roster(NamedTuple):
    """get_instructor's answer: the normalized names, and how many rows it took.

    Kept together because the truncation gate needs the row count while the
    coverage ratio needs the deduped keys — see instructor_roster.
    """
    keys: set
    row_count: int


class BannerPageFailed(RuntimeError):
    """A section page never came back after every retry.

    Raised rather than returned because a short read is indistinguishable from
    a finished term: `iter_sections` stops on an empty page, so a swallowed
    failure hands the caller a truncated section list that looks complete.
    Nothing downstream can detect that — the sanity gates tolerate a 20% drop
    by design, and `prune_stale` would then delete every section the failed
    pages would have carried. Aborting is the only safe answer.
    """


class BannerClient:
    def __init__(self, session=None, sleep=time.sleep, concurrency=CONCURRENCY):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
        })
        self._sleep = sleep
        self.page_size = PAGE_SIZE
        self.max_pages = MAX_PAGES
        self.concurrency = concurrency

    # ── raw requests ──────────────────────────────────────────────────────

    def _check_hard_stop(self, response, path):
        """429/403 anywhere is a hard stop, including on bootstrap and reset.

        No rate limit has ever been observed from this endpoint, so the first one
        is new information about a limit we don't know — quit and re-probe rather
        than retry into it.
        """
        if response.status_code in HARD_STOP_STATUSES:
            raise BannerRateLimited(
                f"{response.status_code} from {path} — no rate limit has ever been "
                f"observed here, so stop and re-probe before running again")

    def _get(self, path, params, attempts=MAX_ATTEMPTS):
        """GET with backoff. Returns None when every attempt failed.

        None and [] are different answers downstream: None is "we don't know
        who teaches this", [] is "Banner says nobody does".
        """
        for attempt in range(1, attempts + 1):
            try:
                r = self.session.get(f"{BASE}/{path}", params=params, timeout=TIMEOUT)
            except requests.RequestException:
                if attempt == attempts:
                    return None
                self._sleep(2 ** attempt)
                continue
            self._check_hard_stop(r, path)
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    return None
            if r.status_code in RETRY_STATUSES and attempt < attempts:
                self._sleep(2 ** attempt)
                continue
            return None
        return None

    def _post(self, path, data=None, attempts=MAX_ATTEMPTS, params=None):
        """POST with the same hard-stop/retry treatment as `_get`.

        A transient 500 here (bootstrap, resetDataForm) is otherwise invisible:
        the session either never gets its cookie or keeps stale filters, and
        every later search returns meaningless rows until a sanity gate aborts
        with a misleading reason.
        """
        r = None
        for attempt in range(1, attempts + 1):
            try:
                r = self.session.post(f"{BASE}/{path}", params=params, data=data, timeout=TIMEOUT)
            except requests.RequestException:
                if attempt == attempts:
                    return None
                self._sleep(2 ** attempt)
                continue
            self._check_hard_stop(r, path)
            if r.status_code in RETRY_STATUSES and attempt < attempts:
                self._sleep(2 ** attempt)
                continue
            return r
        return r

    # ── endpoints ─────────────────────────────────────────────────────────

    def get_terms(self):
        return self._get("classSearch/getTerms",
                         {"searchTerm": "", "offset": 1, "max": 500}) or []

    def bootstrap(self, term_code):
        """Establishes the session cookie. Required before any search."""
        self._post(
            "term/search", params={"mode": "search"},
            data={"term": term_code, "studyPath": "", "studyPathText": "",
                  "startDatepicker": "", "endDatepicker": ""})

    def _reset(self):
        """Clears sticky filters. MUST precede every searchResults call."""
        self._post("classSearch/resetDataForm")

    def search_page(self, term_code, offset):
        """One page of section rows, or None if the request never succeeded.

        The None is deliberate and must not be coalesced to {} — see
        BannerPageFailed. A 200 carrying no `data` is a real answer ("no more
        rows"); a page that never arrived is not.
        """
        self._reset()
        return self._get("searchResults/searchResults",
                         {"txt_term": term_code, "pageOffset": offset,
                          "pageMaxSize": self.page_size})

    def iter_sections(self, term_code):
        """All section rows for a term, deduped on CRN.

        Stops on a short page, on totalCount, or at max_pages — a bug on either
        side must not become an unbounded loop. Raises BannerPageFailed if any
        page fails outright, because stopping early there would silently
        truncate the term instead.
        """
        seen = set()
        offset = 0
        for _ in range(self.max_pages):
            payload = self.search_page(term_code, offset)
            if payload is None:
                raise BannerPageFailed(
                    f"{term_code}: section page at offset {offset} failed every "
                    f"attempt — aborting rather than reporting a truncated term "
                    f"as a complete one")
            rows = payload.get("data") or []
            if not rows:
                return
            for row in rows:
                crn = row.get("courseReferenceNumber")
                if crn in seen:
                    continue        # pagination repeats rows across boundaries
                seen.add(crn)
                yield row
            total = payload.get("totalCount")
            offset += len(rows)
            if len(rows) < self.page_size:
                return
            if total is not None and offset >= total:
                return

    def faculty_for(self, term_code, crn):
        """Instructors for one CRN, or None if the call never succeeded."""
        payload = self._get("searchResults/getFacultyMeetingTimes",
                            {"term": term_code, "courseReferenceNumber": crn})
        if payload is None:
            return None
        return parse_faculty(payload)

    def faculty_for_many(self, term_code, crns):
        """{crn: faculty-or-None}. Concurrency 4 — see banner_api.CONCURRENCY."""
        out = {}
        with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
            for crn, result in zip(crns, ex.map(
                    lambda c: self.faculty_for(term_code, c), crns)):
                out[crn] = result
        return out

    def instructor_roster(self, term_code):
        """Every instructor name Banner lists for the term, normalized.

        One request, and the only independent check that the section scrape
        actually saw the whole term.

        Returns None on transport failure (the request never succeeded),
        distinct from a legitimately empty set (Banner genuinely reports no
        instructors). `_get` collapses both to None; coalescing that to []
        here would make the roster check silently no-op exactly when a
        coordinated Banner change would also have broken get_instructor —
        the one case this gate exists to catch.

        `row_count` is carried alongside the keys because ROSTER_REQUEST_CAP
        caps rows, not distinct people: two rows that normalize to one key
        make len(keys) < the rows Banner actually returned, so a roster
        truncated at exactly the cap would slip past a set-size comparison.
        The truncation gate in banner_scrape compares row_count.
        """
        rows = self._get("classSearch/get_instructor",
                         {"searchTerm": "", "term": term_code,
                          "offset": 1, "max": ROSTER_REQUEST_CAP})
        if rows is None:
            return None
        keys = {normalize_instructor_key(r.get("description"))
                for r in rows if normalize_instructor_key(r.get("description"))}
        return Roster(keys=keys, row_count=len(rows))
