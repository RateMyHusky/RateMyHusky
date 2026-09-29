"""Edition watcher: the one signal that says the whole catalog was replaced.

The failure this guards is silence. `catalog.northeastern.edu` swaps every
course description for a new academic year on a date that has landed anywhere
between mid-July and late August across the last three rollovers (measured
2026-08-13 against Wayback snapshots — see docs/course-data-scope.md), and
nothing announces it. A watcher that returns "unchanged" when it can no longer
find the label is worse than no watcher, so every unreadable case raises rather
than reporting no change.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
import catalog_edition  # noqa: E402
from catalog_edition import (EditionUnreadable, check_edition,  # noqa: E402
                             parse_edition)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "catalog")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


def test_parses_edition_from_the_live_sidebar_markup():
    assert parse_edition(fixture("home_sidebar.html")) == "2025-2026"


def test_reads_the_id_anchor_not_the_first_match():
    """The mobile toggle repeats the label; only the h2 is the source of record.

    A redesign that leaves stale copy in the button must not decide the answer.
    """
    html = fixture("home_sidebar.html").replace(
        "<span>2025-2026 Edition</span>", "<span>2019-2020 Edition</span>")
    assert parse_edition(html) == "2025-2026"


def test_missing_anchor_raises_rather_than_reporting_no_change():
    html = fixture("home_sidebar.html").replace('id="edition"', 'id="masthead"')
    with pytest.raises(EditionUnreadable):
        parse_edition(html)


def test_anchor_without_a_year_label_raises():
    html = fixture("home_sidebar.html").replace(
        '<h2 id="edition" class="sidebar-header"><a href="/">2025-2026 Edition</a></h2>',
        '<h2 id="edition" class="sidebar-header"><a href="/">Academic Catalog</a></h2>')
    with pytest.raises(EditionUnreadable):
        parse_edition(html)


def test_unchanged_edition_reports_no_change():
    result = check_edition(fixture("home_sidebar.html"), "2025-2026")
    assert result.changed is False
    assert result.live == "2025-2026"


def test_new_edition_reports_the_change_with_both_years():
    html = fixture("home_sidebar.html").replace("2025-2026", "2026-2027")
    result = check_edition(html, "2025-2026")
    assert result.changed is True
    assert (result.expected, result.live) == ("2025-2026", "2026-2027")


# --- CLI: the exit code is the whole interface, since CI reads nothing else ---


@pytest.fixture
def state(tmp_path):
    path = tmp_path / "catalog_edition.json"
    catalog_edition.write_state("2025-2026", str(path))
    return str(path)


@pytest.fixture
def serve(monkeypatch):
    """Replace the network boundary and count the calls it receives."""
    calls = []

    def fake_fetch(url=catalog_edition.HOME_URL, session=None):
        calls.append(url)
        return fake_fetch.html

    monkeypatch.setattr(catalog_edition, "fetch_home", fake_fetch)
    fake_fetch.calls = calls
    return fake_fetch


def test_unchanged_edition_exits_zero(state, serve, capsys):
    serve.html = fixture("home_sidebar.html")
    assert catalog_edition.main(["--state", state]) == 0
    assert "Unchanged: 2025-2026" in capsys.readouterr().out


def test_rollover_exits_nonzero_so_ci_goes_red(state, serve, capsys):
    serve.html = fixture("home_sidebar.html").replace("2025-2026", "2026-2027")
    assert catalog_edition.main(["--state", state]) == 1
    assert "2025-2026 -> 2026-2027" in capsys.readouterr().err


def test_one_check_costs_one_request(state, serve):
    """The watcher's entire budget is a single weekly GET; two would double it."""
    serve.html = fixture("home_sidebar.html")
    catalog_edition.main(["--state", state])
    assert len(serve.calls) == 1


def test_unreadable_page_surfaces_rather_than_passing_silently(state, serve):
    serve.html = fixture("home_sidebar.html").replace('id="edition"', 'id="masthead"')
    with pytest.raises(EditionUnreadable):
        catalog_edition.main(["--state", state])


def test_record_writes_the_live_edition_as_the_new_baseline(state, serve):
    serve.html = fixture("home_sidebar.html").replace("2025-2026", "2026-2027")
    assert catalog_edition.main(["--record", "--state", state]) == 0
    assert catalog_edition.read_state(state) == "2026-2027"
