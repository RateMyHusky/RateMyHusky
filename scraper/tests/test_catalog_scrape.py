"""Catalog sweep: the fan-out and the gates that refuse to write.

The catalog's failure mode is not an error, it is a smaller number. A CMS
redesign, a renamed slug or a truncated index all return 200 and simply yield
fewer courses, and a scrape that overwrites 5,199 rows with 400 looks exactly
like a successful run. Every gate here turns one of those into a refusal.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
import catalog_scrape  # noqa: E402
from catalog_api import PageNotFound  # noqa: E402
from catalog_scrape import SanityGateFailed, scrape_catalog  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "catalog")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


def slug(i):
    """Real subject codes are 2-4 letters and never contain a digit."""
    return "abcdefghijklmnopqrstuvwxyz"[i // 26] + "abcdefghijklmnopqrstuvwxyz"[i % 26] + "x"


def index_of(*slugs):
    links = "\n".join(
        f'<li><a href="/course-descriptions/{s}/">Subject {s.upper()} ({s.upper()})</a></li>'
        for s in slugs)
    return f"<div id='textcontainer'><ul>{links}</ul></div>"


def page_with(*codes, subject="CS"):
    blocks = "".join(
        '<div class="courseblock">'
        f'<p class="courseblocktitle noindent"><strong>{subject} {n}.  Course {n}.  (4 Hours)</strong></p>'
        f'<p class="cb_desc">Description for {n}.</p>'
        "</div>"
        for n in codes)
    return f"<div id='textcontainer'>{blocks}</div>"


class FakeClient:
    """Stands in for CatalogClient with no transport at all."""

    def __init__(self, index_html, pages, fail=()):
        self._index = index_html
        self._pages = pages
        self._fail = dict(fail)
        self.requested = []

    def index(self):
        return self._index

    def subject_page(self, slug):
        self.requested.append(slug)
        if slug in self._fail:
            raise self._fail[slug]
        return self._pages[slug]


def client_of(subject_count=210, per_subject=5, **kwargs):
    """A sweep large enough to clear the floor gates, so each test moves one variable."""
    slugs = [slug(i) for i in range(subject_count)]
    pages = {s: page_with(*[f"{1000 + j}" for j in range(per_subject)], subject=s.upper())
             for s in slugs}
    return FakeClient(index_of(*slugs), pages, **kwargs)


# --- the happy path ---

def test_sweeps_every_subject_in_the_index():
    client = client_of(subject_count=210, per_subject=5)
    result = scrape_catalog(client)
    assert len(result.courses) == 210 * 5
    assert len(client.requested) == 210


def test_real_subject_page_parses_end_to_end():
    client = FakeClient(index_of(*[slug(i) for i in range(210)]),
                        {slug(i): fixture("subject_courses.html") for i in range(210)})
    result = scrape_catalog(client)
    assert "CS3000" in {c.code for c in result.courses}


# --- floor gates ---

def test_short_index_aborts():
    """A truncated index is the cheapest way to silently lose half the catalog."""
    with pytest.raises(SanityGateFailed, match="subject"):
        scrape_catalog(client_of(subject_count=12))


def test_empty_index_aborts():
    with pytest.raises(SanityGateFailed):
        scrape_catalog(FakeClient(index_of(), {}))


# --- soft 404s ---

def test_a_few_soft_404s_are_tolerated_and_reported():
    client = client_of(subject_count=210)
    client._fail = {slug(0): PageNotFound(slug(0)), slug(1): PageNotFound(slug(1))}
    result = scrape_catalog(client)
    assert result.not_found == [slug(0), slug(1)]
    assert len(result.courses) == 208 * 5


def test_widespread_soft_404s_abort():
    """Every slug 404ing means the index and the pages disagree — a redesign."""
    client = client_of(subject_count=210)
    client._fail = {slug(i): PageNotFound("gone") for i in range(60)}
    with pytest.raises(SanityGateFailed, match="not found"):
        scrape_catalog(client)


def test_a_page_that_never_loads_aborts_rather_than_shrinking_the_catalog():
    client = client_of(subject_count=210)
    client._fail = {slug(5): RuntimeError("connection reset")}
    with pytest.raises(RuntimeError, match="connection reset"):
        scrape_catalog(client)


# --- comparison against the previous run ---

def test_a_large_drop_against_the_previous_run_aborts():
    client = client_of(subject_count=210, per_subject=5)   # 1050 courses
    with pytest.raises(SanityGateFailed, match="previous"):
        scrape_catalog(client, previous_count=5199)


def test_a_small_drop_is_within_tolerance():
    client = client_of(subject_count=210, per_subject=5)   # 1050 courses
    result = scrape_catalog(client, previous_count=1100)
    assert len(result.courses) == 1050


def test_growth_never_aborts():
    result = scrape_catalog(client_of(subject_count=210, per_subject=5), previous_count=200)
    assert len(result.courses) == 1050


# --- transport ---
#
# Measured against the live site 2026-08-13: a sequential sweep over one
# keep-alive session hit RemoteDisconnected around 40s in. The server drops
# idle connections mid-sweep, so a retry policy that only covers HTTP status
# codes aborts a run that would have finished.

class FakeResponse:
    def __init__(self, status=200, text="ok"):
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise catalog_scrape.requests.HTTPError(f"{self.status_code}")


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.headers = {}
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_dropped_connection_is_retried_rather_than_failing_the_sweep():
    session = FakeSession([
        catalog_scrape.requests.ConnectionError("Remote end closed connection"),
        FakeResponse(text="recovered"),
    ])
    client = catalog_scrape.CatalogClient(session=session, sleep=lambda _: None)
    assert client.subject_page("cs") == "recovered"
    assert session.calls == 2


def test_a_connection_that_never_recovers_still_raises():
    session = FakeSession([catalog_scrape.requests.ConnectionError("down")] * 3)
    client = catalog_scrape.CatalogClient(session=session, sleep=lambda _: None)
    with pytest.raises(catalog_scrape.requests.ConnectionError):
        client.subject_page("cs")
    assert session.calls == 3


def test_retryable_status_is_retried():
    session = FakeSession([FakeResponse(status=503), FakeResponse(text="second try")])
    client = catalog_scrape.CatalogClient(session=session, sleep=lambda _: None)
    assert client.index() == "second try"
    assert session.calls == 2


# --- cross-listing ---

def test_a_code_listed_under_two_subjects_is_kept_once_and_reported():
    slugs = [slug(i) for i in range(210)]
    pages = {s: page_with("1000", subject=s.upper()) for s in slugs}
    pages[slug(1)] = page_with("1000", subject=slug(0).upper())   # same code as the first page
    client = FakeClient(index_of(*slugs), pages)
    result = scrape_catalog(client)
    codes = [c.code for c in result.courses]
    assert len(codes) == len(set(codes))
    assert f"{slug(0).upper()}1000" in result.duplicate_codes
