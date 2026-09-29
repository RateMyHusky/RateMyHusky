"""Parsing catalog.northeastern.edu — no transport, no I/O.

Split from catalog_scrape.py for the same reason banner_api.py is split from
banner_client.py: every rule here is testable against a saved page, and the
rules are where the failures live.

The catalog is static HTML with no auth and no session state, which makes it
the cheapest source in the pipeline — but it lies in three ways that a parser
written from the rendered page will not notice:

1. Subject and number are joined by U+00A0. `"CS 1100".split()` yields one
   token, and a code built by trimming spaces keeps the NBSP, so the join
   against `trace_courses.course_code` silently matches nothing.
2. A subject slug that no longer exists answers **200 with a "Page Not Found"
   body**. `raise_for_status()` passes and the subject contributes zero
   courses, which is indistinguishable from a subject that genuinely has none.
   Measured 2026-08-13: `/course-descriptions/danc/`.
3. Credit hours are free text — `4 Hours`, `1-4 Hours`, `1,2 Hours`,
   `2.25 Hours`, `0 Hours` — so the field cannot be an INT.
"""

import html as html_module
import re
from typing import NamedTuple, Optional

BASE = "https://catalog.northeastern.edu"
INDEX_PATH = "/course-descriptions/"
TIMEOUT = 30
USER_AGENT = "RateMyHusky catalog scraper (+https://ratemyhusky.com)"

# Zero-width space, non-breaking space, and the narrow no-break space the
# catalog's CMS emits inside department names and course titles.
INVISIBLES = {"​": "", " ": " ", " ": " ", "﻿": ""}

SUBJECT_LINK = re.compile(
    r'<a\s+href="/course-descriptions/(?P<slug>[a-z0-9-]+)/"\s*>(?P<label>[^<]+)</a>', re.I)
# "Computer Science (CS)" -> department, subject. The code is always last and
# always parenthesised; department names themselves contain parentheses rarely
# enough that anchoring to the end is safer than a greedy split.
SUBJECT_LABEL = re.compile(r"^(?P<department>.+?)\s*\((?P<subject>[A-Z&\-]{2,8})\)\s*$")

COURSE_BLOCK = re.compile(r'<div class="courseblock">(?P<body>.*?)</div>', re.S)
BLOCK_TITLE = re.compile(r'class="courseblocktitle[^"]*"[^>]*>\s*<strong>(?P<title>.*?)</strong>', re.S)
BLOCK_DESC = re.compile(r'<p class="cb_desc">(?P<desc>.*?)</p>', re.S)
EXTRA_FIELD = re.compile(
    r"<strong>(?P<label>Prerequisite\(s\)|Corequisite\(s\)|Attribute\(s\)):\s*</strong>(?P<value>.*?)</p>",
    re.S)

# "CS 1100.  Computer Science and Its Applications.  (4 Hours)"
TITLE = re.compile(
    r"^(?P<subject>[A-Z][A-Z&\- ]*?)\s+(?P<number>\d{3,4}[A-Z]?)\.\s+"
    r"(?P<name>.+?)\.\s+\((?P<hours>[^)]*)\)\s*$", re.S)

NUMBER = re.compile(r"\d+(?:\.\d+)?")
# Inline tags are deleted, block tags become a space. Prerequisite text wraps
# course codes in <a> mid-sentence — "((<a>CS 2100</a> with a minimum grade" —
# so substituting a space for every tag yields "(( CS 2100", which is not what
# the page renders and not what gets displayed verbatim.
BLOCK_TAGS = re.compile(r"</?(?:p|div|br|li|ul|ol|tr|td|th|h\d)\b[^>]*>", re.I)
TAGS = re.compile(r"<[^>]+>")
NOT_FOUND_MARKERS = ("Page Not Found", "was not found in the catalog")


class PageNotFound(RuntimeError):
    """A subject page answered 200 with a not-found body.

    Raised rather than returning [] because the caller cannot tell the two
    apart, and "this subject has no courses" is a legitimate-looking answer
    that would quietly shrink the catalog by one subject per retired slug.
    """


class CatalogParseError(RuntimeError):
    """A course block did not match the shape every block has had.

    Not tolerated per-block: a title format change affects every course on the
    page, so skipping the unparseable ones would write a partial subject and
    call it a success.
    """


class Subject(NamedTuple):
    slug: str
    subject: str
    department: str


class Course(NamedTuple):
    code: str
    subject: str
    number: str
    name: str
    credit_hours: str
    credit_min: Optional[float]
    credit_max: Optional[float]
    description: Optional[str]
    prerequisites: Optional[str]
    corequisites: Optional[str]
    nupath: list
    subject_slug: str


def clean(text):
    """Entity-decode, drop tags, normalise invisible characters, collapse space."""
    if text is None:
        return None
    text = BLOCK_TAGS.sub(" ", text)
    text = TAGS.sub("", text)
    text = html_module.unescape(text)
    for bad, good in INVISIBLES.items():
        text = text.replace(bad, good)
    return " ".join(text.split())


def parse_subject_index(index_html):
    """Every subject page linked from /course-descriptions/."""
    subjects = []
    seen = set()
    for match in SUBJECT_LINK.finditer(index_html):
        slug = match.group("slug")
        if slug in seen:
            continue
        label = SUBJECT_LABEL.match(clean(match.group("label")))
        if not label:
            continue
        seen.add(slug)
        subjects.append(Subject(slug=slug, subject=label.group("subject"),
                                department=label.group("department")))
    return subjects


def parse_credit_hours(text):
    """(min, max) from the free-text hours field, or (None, None).

    '1-4 Hours' and '1,2 Hours' both mean a range to a student choosing a
    section; the distinction between them is not worth a column.
    """
    numbers = [float(n) for n in NUMBER.findall(text or "")]
    if not numbers:
        return (None, None)
    return (min(numbers), max(numbers))


def parse_courses(page_html, subject_slug):
    """Every course on one subject page."""
    if any(marker in page_html for marker in NOT_FOUND_MARKERS):
        raise PageNotFound(f"/course-descriptions/{subject_slug}/ returned a not-found body")

    courses = []
    for block in COURSE_BLOCK.finditer(page_html):
        body = block.group("body")

        title_match = BLOCK_TITLE.search(body)
        if not title_match:
            raise CatalogParseError(f"{subject_slug}: course block with no title")

        title = TITLE.match(clean(title_match.group("title")))
        if not title:
            raise CatalogParseError(
                f"{subject_slug}: unrecognised title {clean(title_match.group('title'))!r}")

        desc_match = BLOCK_DESC.search(body)
        extras = {m.group("label"): clean(m.group("value")) for m in EXTRA_FIELD.finditer(body)}
        attributes = extras.get("Attribute(s)")

        hours = title.group("hours")
        credit_min, credit_max = parse_credit_hours(hours)
        subject = title.group("subject").replace(" ", "")

        courses.append(Course(
            code=f"{subject}{title.group('number')}",
            subject=subject,
            number=title.group("number"),
            name=clean(title.group("name")),
            credit_hours=hours,
            credit_min=credit_min,
            credit_max=credit_max,
            description=clean(desc_match.group("desc")) if desc_match else None,
            prerequisites=extras.get("Prerequisite(s)") or None,
            corequisites=extras.get("Corequisite(s)") or None,
            nupath=parse_attributes(attributes),
            subject_slug=subject_slug,
        ))
    return courses


def parse_attributes(text):
    """['Analyzing/Using Data', ...] from 'NUpath X,  NUpath Y'.

    Non-NUpath attributes are kept verbatim rather than dropped — the label set
    is the registrar's, and silently discarding an unrecognised one would hide
    the fact that it appeared.
    """
    if not text:
        return []
    labels = []
    for part in text.split(","):
        label = part.strip()
        if not label:
            continue
        labels.append(label[len("NUpath"):].strip() if label.startswith("NUpath") else label)
    return labels
