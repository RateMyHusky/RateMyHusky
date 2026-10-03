"""Transport behaviour, driven by a fake session. No sockets.

The three things that can silently corrupt a run all live here: the
resetDataForm call before every search, the pagination loop, and the
retry/hard-stop split. Each gets a test.
"""
import json
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
from banner_client import (BannerClient, BannerPageFailed,  # noqa: E402
                           BannerRateLimited, BannerRequestFailed)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "banner")


def fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


class FakeResp:
    def __init__(self, payload=None, status=200, text="true"):
        self._payload = payload
        self.status_code = status
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Records every call so tests can assert on ordering."""

    def __init__(self, responses=None):
        self.calls = []
        self.headers = {}
        self.responses = responses or {}

    def _route(self, method, url, **kw):
        self.calls.append((method, url.rsplit("/", 1)[-1], kw.get("params"), kw.get("data")))
        key = url.rsplit("/", 1)[-1]
        r = self.responses.get(key, FakeResp({}))
        return r(self) if callable(r) else r

    def get(self, url, **kw):
        return self._route("GET", url, **kw)

    def post(self, url, **kw):
        return self._route("POST", url, **kw)


def endpoints_called(session):
    return [c[1] for c in session.calls]


def test_bootstrap_posts_term_search():
    s = FakeSession({"search": FakeResp({})})
    BannerClient(session=s).bootstrap("202710")
    assert endpoints_called(s) == ["search"]
    assert s.calls[0][3]["term"] == "202710"


def test_bootstrap_retries_transient_500():
    calls = [FakeResp(status=500), FakeResp({})]
    s = FakeSession({"search": lambda _s: calls.pop(0)})
    slept = []
    BannerClient(session=s, sleep=slept.append).bootstrap("202710")
    assert endpoints_called(s).count("search") == 2
    assert len(slept) == 1


def test_bootstrap_hard_stops_on_429():
    """A rate limit on the FIRST call must not be swallowed — otherwise the run
    continues without a session cookie and fails later with a misleading error."""
    s = FakeSession({"search": FakeResp(status=429)})
    with pytest.raises(BannerRateLimited):
        BannerClient(session=s).bootstrap("202710")


def test_reset_hard_stops_on_403():
    s = FakeSession({"resetDataForm": FakeResp(status=403)})
    with pytest.raises(BannerRateLimited):
        BannerClient(session=s).search_page("202710", 0)


def test_post_retries_a_connection_error_then_succeeds():
    """_reset()/bootstrap() run before every one of ~20 section pages. A single
    connection reset must not kill a 12-minute run — _post must retry a
    RequestException exactly like _get does."""
    calls = [requests.exceptions.ConnectionError("reset"), FakeResp({})]

    def responder(_s):
        item = calls.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    s = FakeSession({"search": responder})
    slept = []
    BannerClient(session=s, sleep=slept.append).bootstrap("202710")
    assert endpoints_called(s).count("search") == 2
    assert len(slept) == 1


def test_post_persistent_connection_error_returns_none_not_raises():
    """Every attempt fails with a RequestException: _post must return None,
    the same "we don't know" contract _get has, instead of propagating a
    traceback that would kill the whole scrape."""
    def always_raises(_s):
        raise requests.exceptions.ConnectionError("reset")

    s = FakeSession({"resetDataForm": always_raises})
    client = BannerClient(session=s, sleep=lambda _: None)
    assert client._post("classSearch/resetDataForm") is None


def test_search_page_resets_form_first():
    """Without resetDataForm, Banner returns the PREVIOUS query's rows."""
    s = FakeSession({
        "resetDataForm": FakeResp(text="true"),
        "searchResults": FakeResp(fixture("search_page.json")),
    })
    BannerClient(session=s).search_page("202710", 0)
    assert endpoints_called(s) == ["resetDataForm", "searchResults"]


def test_iter_sections_paginates_until_total_count():
    page1 = {"totalCount": 3, "data": [{"courseReferenceNumber": str(i)} for i in range(2)]}
    page2 = {"totalCount": 3, "data": [{"courseReferenceNumber": "2"}]}
    pages = iter([page1, page2])
    s = FakeSession({
        "resetDataForm": FakeResp(text="true"),
        "searchResults": lambda _s: FakeResp(next(pages)),
    })
    client = BannerClient(session=s)
    client.page_size = 2
    rows = list(client.iter_sections("202710"))
    assert [r["courseReferenceNumber"] for r in rows] == ["0", "1", "2"]
    assert endpoints_called(s).count("resetDataForm") == 2


def test_iter_sections_dedupes_repeated_crns():
    """Pagination can repeat rows across page boundaries."""
    page1 = {"totalCount": 3, "data": [{"courseReferenceNumber": "1"}, {"courseReferenceNumber": "2"}]}
    page2 = {"totalCount": 3, "data": [{"courseReferenceNumber": "2"}, {"courseReferenceNumber": "3"}]}
    pages = iter([page1, page2])
    s = FakeSession({
        "resetDataForm": FakeResp(text="true"),
        "searchResults": lambda _s: FakeResp(next(pages)),
    })
    client = BannerClient(session=s)
    client.page_size = 2
    rows = list(client.iter_sections("202710"))
    assert [r["courseReferenceNumber"] for r in rows] == ["1", "2", "3"]


def test_iter_sections_raises_when_distinct_crns_fall_short_of_total_count():
    """Banner ignoring pageOffset and serving the same page again would read
    as 500 of 9,000 sections; the distinct count against totalCount catches it."""
    page = {"totalCount": 4, "data": [{"courseReferenceNumber": "1"}, {"courseReferenceNumber": "2"}]}
    s = FakeSession({
        "resetDataForm": FakeResp(text="true"),
        "searchResults": FakeResp(page),
    })
    client = BannerClient(session=s)
    client.page_size = 2
    with pytest.raises(BannerPageFailed, match="totalCount 4"):
        list(client.iter_sections("202710"))


def test_iter_sections_raises_on_a_short_page_before_total_count():
    page = {"totalCount": 999, "data": [{"courseReferenceNumber": "1"}]}
    s = FakeSession({
        "resetDataForm": FakeResp(text="true"),
        "searchResults": FakeResp(page),
    })
    client = BannerClient(session=s)
    client.page_size = 500
    with pytest.raises(BannerPageFailed, match="1 of 999"):
        list(client.iter_sections("202710"))


def test_iter_sections_raises_on_success_false_mid_term():
    """The reviewer's repro: 500 of 1,200 rows, then success: false. That used
    to end the loop as if the term were finished."""
    pages = iter([{"totalCount": 1200, "data": [{"courseReferenceNumber": str(i)} for i in range(2)]},
                  {"success": False, "data": None}])
    s = FakeSession({
        "resetDataForm": FakeResp(text="true"),
        "searchResults": lambda _s: FakeResp(next(pages)),
    })
    client = BannerClient(session=s)
    client.page_size = 2
    with pytest.raises(BannerPageFailed, match="success: false"):
        list(client.iter_sections("202710"))


def test_iter_sections_raises_on_an_empty_page_before_total_count():
    pages = iter([{"totalCount": 1200, "data": [{"courseReferenceNumber": str(i)} for i in range(2)]},
                  {"totalCount": 1200, "data": []}])
    s = FakeSession({
        "resetDataForm": FakeResp(text="true"),
        "searchResults": lambda _s: FakeResp(next(pages)),
    })
    client = BannerClient(session=s)
    client.page_size = 2
    with pytest.raises(BannerPageFailed):
        list(client.iter_sections("202710"))


def test_iter_sections_stops_on_short_page_without_a_total_count():
    """With no totalCount, a page shorter than page_size is the only end signal.

    Asserts the request count, not the row count: row count is confounded by CRN
    dedup, so it stays 1 even if this termination branch is deleted entirely.
    """
    page = {"data": [{"courseReferenceNumber": "1"}]}
    s = FakeSession({
        "resetDataForm": FakeResp(text="true"),
        "searchResults": FakeResp(page),
    })
    client = BannerClient(session=s)
    client.page_size = 500
    rows = list(client.iter_sections("202710"))
    assert len(rows) == 1
    assert endpoints_called(s).count("searchResults") == 1


def test_iter_sections_raises_at_max_pages():
    """Circuit breaker against an API bug that never stops returning rows. It
    raises: stopping quietly at the cap would hand back a truncated term."""
    n = [0]

    def full_page(_s):
        n[0] += 1
        return FakeResp({"totalCount": 10**9,
                         "data": [{"courseReferenceNumber": f"{n[0]}-{i}"} for i in range(2)]})

    s = FakeSession({"resetDataForm": FakeResp(text="true"), "searchResults": full_page})
    client = BannerClient(session=s)
    client.page_size = 2
    client.max_pages = 3
    with pytest.raises(BannerPageFailed, match="3-page cap"):
        list(client.iter_sections("202710"))
    assert n[0] == 3


def test_iter_sections_raises_when_a_page_never_comes_back():
    """A failed page must abort, not look like the end of the term.

    `_get` returns None when every attempt failed. If that collapses to an
    empty payload, `iter_sections` sees no rows and returns — the caller gets
    a short read indistinguishable from a fully-scraped term, and
    prune_stale then deletes every section that was never fetched.
    """
    pages = [FakeResp({"totalCount": 4,
                       "data": [{"courseReferenceNumber": str(i)} for i in range(2)]}),
             FakeResp(status=500)]

    def responder(_s):
        return pages.pop(0) if pages else FakeResp(status=500)

    s = FakeSession({"resetDataForm": FakeResp(text="true"), "searchResults": responder})
    client = BannerClient(session=s, sleep=lambda _: None)
    client.page_size = 2
    with pytest.raises(BannerPageFailed):
        list(client.iter_sections("202710"))


def test_iter_sections_raises_when_the_very_first_page_fails():
    """Page 0 failing is the same defect, and would otherwise surface
    downstream as the misleading "0 sections returned"."""
    s = FakeSession({"resetDataForm": FakeResp(text="true"),
                     "searchResults": FakeResp(status=500)})
    client = BannerClient(session=s, sleep=lambda _: None)
    with pytest.raises(BannerPageFailed):
        list(client.iter_sections("202710"))


def test_iter_sections_treats_a_valid_empty_page_as_the_end():
    """A 200 carrying no `data` is Banner saying "nothing more", which is a
    different answer from a page that never arrived — it must not raise."""
    s = FakeSession({"resetDataForm": FakeResp(text="true"),
                     "searchResults": FakeResp({"totalCount": 0, "data": []})})
    assert list(BannerClient(session=s).iter_sections("202710")) == []


def test_429_raises_hard_stop():
    """Never retried: no 429 has ever been observed, so the first one is news."""
    s = FakeSession({"getFacultyMeetingTimes": FakeResp(status=429)})
    with pytest.raises(BannerRateLimited):
        BannerClient(session=s).faculty_for("202710", "10324")


def test_403_raises_hard_stop():
    s = FakeSession({"getFacultyMeetingTimes": FakeResp(status=403)})
    with pytest.raises(BannerRateLimited):
        BannerClient(session=s).faculty_for("202710", "10324")


def test_500_is_retried_then_succeeds():
    calls = [FakeResp(status=500), FakeResp(fixture("fmt_single.json"))]
    s = FakeSession({"getFacultyMeetingTimes": lambda _s: calls.pop(0)})
    slept = []
    got = BannerClient(session=s, sleep=slept.append).faculty_for("202710", "10324")
    assert [f["instructor_key"] for f in got] == ["annie witte"]
    assert len(slept) == 1


def test_persistent_failure_returns_none_not_empty():
    """None means "unknown", [] means "confirmed nobody". The gate needs both."""
    s = FakeSession({"getFacultyMeetingTimes": FakeResp(status=500)})
    assert BannerClient(session=s, sleep=lambda _: None).faculty_for("202710", "10324") is None


def test_faculty_for_many_maps_crn_to_result():
    s = FakeSession({"getFacultyMeetingTimes": FakeResp(fixture("fmt_single.json"))})
    got = BannerClient(session=s).faculty_for_many("202710", ["1", "2"])
    assert set(got) == {"1", "2"}
    assert got["1"][0]["instructor_key"] == "annie witte"


def test_user_agent_identifies_the_project():
    s = FakeSession()
    BannerClient(session=s)
    assert "RateMyHusky" in s.headers["User-Agent"]


def test_instructor_roster_normalizes_names():
    s = FakeSession({"get_instructor": FakeResp(
        [{"code": "1", "description": "Witte, Annie"},
         {"code": "2", "description": "Hurley, Patrick"}])})
    assert BannerClient(session=s).instructor_roster("202710").keys == {
        "annie witte", "patrick hurley"}


def test_instructor_roster_reports_rows_returned_not_unique_names():
    """The truncation gate compares against get_instructor's max= request cap,
    which caps ROWS. Two rows normalizing to one key would make a set-size
    comparison undercount, so a roster truncated at exactly the cap could slip
    through the gate. row_count is what the cap is actually about.
    """
    rows = [{"description": "Witte, Annie"},
            {"description": "Witte, Annie"},      # duplicate row, one key
            {"description": "Hurley, Patrick"}]
    s = FakeSession({"get_instructor": FakeResp(rows)})
    roster = BannerClient(session=s).instructor_roster("202710")
    assert roster.keys == {"annie witte", "patrick hurley"}
    assert roster.row_count == 3


def test_instructor_roster_returns_none_on_transport_failure():
    """None (transport failure) must stay distinguishable from a legitimately
    empty roster — the scrape_term gate treats them very differently."""
    s = FakeSession({"get_instructor": FakeResp(status=500)})
    assert BannerClient(session=s, sleep=lambda _: None).instructor_roster("202710") is None


# ── bootstrap / reset must not fail silently ─────────────────────────────

def test_reset_that_keeps_failing_raises_instead_of_searching():
    """A failed resetDataForm leaves the previous query's filters in place, and
    the search then returns the wrong rows with a 200. Never search after one."""
    s = FakeSession({"resetDataForm": FakeResp(status=500),
                     "searchResults": FakeResp(fixture("search_page.json"))})
    client = BannerClient(session=s, sleep=lambda _: None)
    with pytest.raises(BannerRequestFailed, match="resetDataForm"):
        client.search_page("202710", 0)
    assert "searchResults" not in endpoints_called(s)


def test_bootstrap_with_no_response_raises():
    def always_raises(_s):
        raise requests.exceptions.ConnectionError("reset")

    s = FakeSession({"search": always_raises})
    with pytest.raises(BannerRequestFailed, match="no response"):
        BannerClient(session=s, sleep=lambda _: None).bootstrap("202710")


def test_roster_reports_names_more_than_one_row_normalizes_to():
    rows = [{"description": "Wang, Wei"}, {"description": "Wang,  Wei"},
            {"description": "Witte, Annie"}]
    s = FakeSession({"get_instructor": FakeResp(rows)})
    roster = BannerClient(session=s).instructor_roster("202710")
    assert roster.keys == {"wei wang", "annie witte"}
    assert roster.row_count == 3
    assert roster.duplicate_keys == {"wei wang"}
