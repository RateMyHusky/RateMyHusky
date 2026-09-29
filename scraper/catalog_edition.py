"""Watch catalog.northeastern.edu for the annual edition rollover.

One request a week. When `catalog.northeastern.edu` replaces the 2025-2026
edition with 2026-2027, every course description on the site changes at once
and nothing announces it. Measured 2026-08-13 against Wayback snapshots, the
rollover landed 2025-07-12..2025-08-02, 2024-07-03..2024-08-01 and
2023-08-03..2023-09-27 — a six-week window that moves year to year, which is
why this polls instead of running on a date.

The label lives in the sidebar heading, present on every page:

    <h2 id="edition" class="sidebar-header"><a href="/">2025-2026 Edition</a></h2>

Usage
-----
    python catalog_edition.py            # compare live against the recorded edition
    python catalog_edition.py --record   # accept the live edition as the new baseline
"""

import argparse
import json
import os
import re
import sys
from datetime import date
from typing import NamedTuple

import requests

HOME_URL = "https://catalog.northeastern.edu/"
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog_edition.json")
TIMEOUT = 30
USER_AGENT = "RateMyHusky edition watcher (+https://ratemyhusky.com)"

# The id is the contract, not the position: the mobile toggle button repeats the
# same label with no id, so matching the first year on the page would let stale
# button copy decide the answer.
EDITION_ANCHOR = re.compile(r'<(h\d)[^>]*\bid="edition"[^>]*>(.*?)</\1>', re.S | re.I)
YEAR_LABEL = re.compile(r"\b(\d{4}-\d{4})\b")
TAGS = re.compile(r"<[^>]+>")


class EditionUnreadable(RuntimeError):
    """The label is gone or unrecognisable.

    Raised rather than returned as "unchanged" because those two are the same
    HTTP 200 to a caller. A redesign that renames the anchor would otherwise
    park this watcher in a permanent quiet state — the exact silence it exists
    to break.
    """


class EditionCheck(NamedTuple):
    expected: str
    live: str

    @property
    def changed(self):
        return self.expected != self.live


def parse_edition(html):
    """The academic year the site is currently serving, e.g. '2025-2026'."""
    anchor = EDITION_ANCHOR.search(html)
    if not anchor:
        raise EditionUnreadable(
            'no element carrying id="edition" — the catalog layout changed')

    text = TAGS.sub(" ", anchor.group(2))
    year = YEAR_LABEL.search(text)
    if not year:
        raise EditionUnreadable(
            f"id=\"edition\" holds no YYYY-YYYY label: {' '.join(text.split())!r}")
    return year.group(1)


def check_edition(html, expected):
    return EditionCheck(expected=expected, live=parse_edition(html))


def fetch_home(url=HOME_URL, session=None):
    session = session or requests
    response = session.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.text


def read_state(path=STATE_PATH):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["edition"]


def write_state(edition, path=STATE_PATH, today=None):
    today = today or date.today()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"edition": edition, "recorded": today.isoformat()}, fh, indent=2)
        fh.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--record", action="store_true",
                        help="write the live edition to the state file as the new baseline")
    parser.add_argument("--url", default=HOME_URL)
    parser.add_argument("--state", default=STATE_PATH)
    args = parser.parse_args(argv)

    html = fetch_home(args.url)

    if args.record:
        live = parse_edition(html)
        write_state(live, args.state)
        print(f"Recorded {live} as the baseline in {args.state}")
        return 0

    result = check_edition(html, read_state(args.state))
    if result.changed:
        print(f"NEW EDITION: {result.expected} -> {result.live}", file=sys.stderr)
        return 1
    print(f"Unchanged: {result.live}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
