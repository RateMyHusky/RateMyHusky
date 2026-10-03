"""NUBanner JSON API — constants and pure parsing.

The endpoints are the unauthenticated JSON ones behind Northeastern's public
Find Classes UI (https://nubanner.neu.edu/StudentRegistrationSsb/ssb). No
credentials, no HTML parsing.

Nothing in this module touches the network or the database, because the parsing
is where the bugs are and it is only testable in isolation.

Measured against the live API 2026-08-04:
  - emailAddress is null for ~85% of faculty entries. Identity is the name.
  - ~13% of sections have no faculty at all (TBA).
  - searchResults never carries faculty, in `faculty` or in `meetingsFaculty`.
  - getTerms suffixes closed terms with "(View Only)".
  - Law and CPS sections live on parallel term codes for the same season.
"""

import html
import re
import unicodedata
from datetime import datetime

BASE = "https://nubanner.neu.edu/StudentRegistrationSsb/ssb"
USER_AGENT = "RateMyHusky/1.0 (+https://github.com/gRain-is-grainy/RateMyHusky)"

PAGE_SIZE = 500     # server-side hard cap; asking for 1000 returns 500
CONCURRENCY = 4     # measured optimum: 1,065 req/min. 6 and 8 are slower.
# The weekly refresh has no reason to run at that optimum against the live
# registration system: ~7k requests per open term, every Monday. Half the
# rate roughly doubles the run (measured 11m57s per full term at 4).
WEEKLY_CONCURRENCY = 2
TIMEOUT = 30        # matches fetch_lite.py
MAX_PAGES = 40      # circuit breaker: 40 * 500 = 20k sections, ~2x the largest term

# get_instructor's own server-side request cap (banner_client.instructor_roster
# passes this as max=). banner_scrape's roster-truncation gate compares the
# returned roster size against this SAME constant: raising it here to
# accommodate roster growth (production already sits at 3,005 instructors)
# automatically raises the gate's threshold too, so the two stay coupled
# instead of silently drifting apart across the module boundary.
ROSTER_REQUEST_CAP = 6000

# Not a class a student picks a professor for. Individual Instruction is
# thesis/directed-study supervision: 1,384 of 7,012 Spring 2026 sections, 1,148
# of them with two students or fewer. COOP Placement is a job. Their section rows
# are still stored (they cost nothing extra — they arrive on the same search
# pages), but their instructors are never looked up, which skips ~20% of the
# per-CRN requests, and they are never displayed as teaching.
#
# "Off-campus instruction" is deliberately NOT here: Dialogue of Civilizations
# and other study-abroad courses are taught by regular faculty under it.
NON_TEACHING_SCHEDULE_TYPES = frozenset({"individual instruction", "coop placement"})

# Banner uses campusDescription for things that are not places. Measured on the
# real Fall 2026 load: 207 teaching rows carry "No campus, no room needed", which
# would render on the chip as "· No campus, no room needed". "Online" and
# "Study Abroad" ARE meaningful to a student and stay.
NON_PLACE_CAMPUSES = frozenset({"no campus, no room needed"})

_SEASON_RE = re.compile(r"\b(Fall|Spring)\s+(\d{4})\b", re.IGNORECASE)
_VIEW_ONLY = "(view only)"

# Every season spelling getTerms used between 2009 and 2026. "Summer Full",
# "Summer 1" and "Summer 2" are the main campus's three summer sessions; CPS
# and Law run plain "Summer". Longest alternatives first, or "Summer" would
# swallow "Summer Full 2025" as season "Summer", year unparseable.
_TERM_RE = re.compile(
    r"^\s*(Summer Full|Summer 1|Summer 2|Summer|Fall|Spring|Winter)\s+(\d{4})\s*(.*)$",
    re.IGNORECASE)


# CPS runs a Winter quarter (January to March) alongside the Spring semester.
# For "when is this course offered" and for the teaching chip it is the same
# part of the year, so it folds into Spring rather than vanishing: a course that
# runs every Winter quarter would otherwise read "Not offered recently".
_PATTERN_SEASON = {"Winter": "Spring"}


def pattern_season(season_group):
    """season_group -> the season it counts as for offering patterns and the chip."""
    return _PATTERN_SEASON.get(season_group, season_group)


def normalize_instructor_key(display_name):
    """Banner's "Last, First M" -> "first m last".

    Must agree with backend/pipeline/names.normalize_name (NFKD -> ASCII, lower, collapse
    whitespace) applied to "First Last", because that is what professors_catalog
    stores in name_key. The comma flip is the only extra step; no punctuation is
    stripped here, or "St. Onge" and "St Onge" would key to different people than
    normalize_name does.

    displayName is HTML-escaped the same way courseTitle is (see parse_section):
    "O'Connell" arrives as "O&#39;Connell". Unescaping is not cosmetic here —
    the catalog side keeps a literal apostrophe, so without this every
    apostrophe surname keys to something no catalog row can equal. Measured on
    the real Fall 2026 load: 13 professors unmatched for this reason alone, and
    zero new ambiguity once decoded.

    The unescape must precede the NFKD/ascii fold, not follow it: "&#233;" is a
    pure-ASCII spelling of é, so folding first would preserve the entity's
    digits and yield "jos233" instead of "jose".
    """
    if not display_name:
        return ""
    s = html.unescape(str(display_name)).strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    if "," in s:
        last, _, first = s.partition(",")
        s = f"{first.strip()} {last.strip()}"
    return re.sub(r"\s+", " ", s).strip()


def clean_term_desc(desc):
    """"Fall 2026 Semester" / "Fall 2025 Law Semester (View Only)" -> "Fall 2026".

    Reduced to season + year so Law/CPS siblings collapse onto one display term.
    """
    if not desc:
        return ""
    m = _SEASON_RE.search(str(desc))
    if not m:
        return str(desc).strip()
    return f"{m.group(1).title()} {m.group(2)}"


def parse_term(desc):
    """getTerms description -> its parts, or None if it isn't a term name.

    "Summer Full 2025 Semester (View Only)" ->
        {"label": "Summer Full 2025", "season": "Summer Full",
         "season_group": "Summer", "year": 2025, "track": "Semester",
         "view_only": True}

    `label` is what a student reads; `season_group` folds the three summer
    sessions together, which is the grain "is this offered in summer" needs.
    `track` keeps Law and CPS apart from the main-campus Semester term.
    """
    if not desc:
        return None
    text = str(desc).strip()
    view_only = _VIEW_ONLY in text.lower()
    if view_only:
        text = text[:text.lower().index(_VIEW_ONLY)].strip()
    m = _TERM_RE.match(text)
    if not m:
        return None
    season = " ".join(w.capitalize() for w in m.group(1).split())
    year = int(m.group(2))
    return {
        "label": f"{season} {year}",
        "season": season,
        "season_group": season.split()[0],
        "year": year,
        "track": m.group(3).strip() or None,
        "view_only": view_only,
    }


def _num(value):
    """An int or None. Banner sends counts as ints, but None and "" both occur."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _credit_hours(row):
    """(low, high). Variable-credit courses carry both; fixed ones only low.

    creditHours is null on every row sampled (2012, 2018, 2026), so
    creditHourLow is the real value and creditHours only a fallback.
    """
    low = row.get("creditHourLow")
    if low is None:
        low = row.get("creditHours")
    high = row.get("creditHourHigh")
    as_float = lambda v: float(v) if v not in (None, "") else None  # noqa: E731
    return as_float(low), as_float(high)


def parse_section(row):
    """One searchResults row -> the columns banner_sections stores.

    Everything here comes from the searchResults page itself, so none of it
    costs a request beyond the page. Enrollment on a closed (View Only) term is
    the final headcount; on an open one it is a snapshot that moves until
    add/drop ends, which is why class-size averages only read closed terms.

    Only what the site shows is kept: who, what, when, how big. Meeting times,
    rooms, seats, waitlists, section links and attributes (NUpath) are
    registration data — SearchNEU's job — and are deliberately never stored.
    """
    low, high = _credit_hours(row)
    return {
        "term_code": row.get("term"),
        "term_desc": clean_term_desc(row.get("termDesc")),
        "crn": row.get("courseReferenceNumber"),
        "subject": row.get("subject"),
        "subject_course": row.get("subjectCourse"),
        "course_number": row.get("courseNumber"),
        "section": row.get("sequenceNumber"),
        # Banner HTML-escapes titles: "Fin Accounting &amp; Reporting".
        "course_title": html.unescape(row.get("courseTitle") or ""),
        "campus": row.get("campusDescription"),
        "instructional_method": row.get("instructionalMethodDescription"),
        "schedule_type": row.get("scheduleTypeDescription"),
        "credit_hours_low": low,
        "credit_hours_high": high,
        "enrollment": _num(row.get("enrollment")),
    }


def parse_faculty(payload):
    """getFacultyMeetingTimes -> one entry per distinct instructor.

    fmt[] holds one block per meeting pattern, so a single instructor recurs
    across blocks and must be deduped. Deduped on the normalized name rather
        than bannerId: bannerId is a per-term row index and is not stable, and
    the name is the key everything downstream joins on anyway.

    is_primary is OR'd across blocks — a person listed as primary in any block
    is primary. Email addresses are deliberately dropped: nothing uses them,
    and Banner only has one for ~15% of faculty anyway.
    """
    seen = {}
    for block in payload.get("fmt") or []:
        for f in block.get("faculty") or []:
            name = (f.get("displayName") or "").strip()
            key = normalize_instructor_key(name)
            if not key:
                continue
            entry = seen.get(key)
            if entry is None:
                seen[key] = {
                    "instructor_name": name,
                    "instructor_key": key,
                    "is_primary": bool(f.get("primaryIndicator")),
                }
            else:
                entry["is_primary"] = entry["is_primary"] or bool(f.get("primaryIndicator"))
    return list(seen.values())


def section_end_dates(rows):
    """Every meetingTime.endDate on these rows, as dates.

    searchResults carries real term boundaries, so "is this term actually in the
    future" is observable rather than guessed. Used only to validate the term
    picker's choice.
    """
    out = []
    for row in rows:
        for meeting in row.get("meetingsFaculty") or []:
            raw = (meeting.get("meetingTime") or {}).get("endDate")
            if raw:
                try:
                    out.append(datetime.strptime(raw, "%m/%d/%Y").date())
                except ValueError:
                    continue
    return out


def select_season(terms):
    """getTerms rows -> (display term, [term codes]) for the season to scrape.

    Banner marks closed terms "(View Only)" itself, so no clock and no date
    arithmetic are needed. Of 269 terms on 2026-08-04, exactly three lacked the
    marker: Fall 2026, Summer 2026, and Summer 2026 CPS.

    Returns every code for the chosen season, not one: Law and CPS run on
    parallel term rows ("Fall 2025 Law Semester", "Fall 2025 CPS Quarter"), and
    taking only the plain Semester row would silently omit every Law and CPS
    professor.

    Earliest open season wins. During Fall, Spring is usually open too, and the
    term in progress is the truthful answer.
    """
    seasons = {}
    for t in terms:
        desc = t.get("description") or ""
        if _VIEW_ONLY in desc.lower():
            continue
        m = _SEASON_RE.search(desc)
        if not m:                      # Summer, Winter, or something unparseable
            continue
        code = t.get("code")
        if code is None:                # malformed row, missing its own code
            continue
        seasons.setdefault(clean_term_desc(desc), []).append(str(code))

    if not seasons:
        raise ValueError("no open Fall/Spring term in getTerms")

    # Codes sort chronologically as integers; the season's lowest code orders it.
    chosen = min(seasons, key=lambda d: min(int(c) for c in seasons[d]))
    return chosen, sorted(seasons[chosen], key=int)
