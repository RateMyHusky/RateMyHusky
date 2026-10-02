"""Who taught what, when, and to how big a room — from NUBanner.

Reads the tables scraper/match_banner_instructors.py builds (Fall 2021 on):

  banner_course_offerings     one row per course: offering pattern, class size,
                              credits, whether it is on the current schedule
  banner_course_instructors   one row per (course, instructor)
  professor_teaching          the current season's chip, one row per professor

Scope is deliberate: this is context for reviews, not a registration tool.
Seats, waitlists, NUpath, meeting times and the course's format are
SearchNEU's job and never leave the scraper.

Pure functions over injected `query`/`query_one`, like professor_full.py.
They raise when the tables are missing; server.py turns that into "no
history" so a page never fails over a decoration.
"""

import re
from datetime import datetime, timedelta, timezone

# Courses replaced by a redesigned one, not renumbered: the content changed,
# so reviews stay on the old code and the two pages link to each other
# instead. Khoury's published mapping for the Fall 2025 intro sequence:
# khoury.northeastern.edu/current-undergraduate-students/introductory-computing-courses-at-khoury-college
# A pure renumber (same course, new code) belongs in the scraper's
# COURSE_RENAMES instead, where the history is merged.
COURSE_SUCCESSORS = {
    "CS2500": ("CS2000", "Fall 2025"),
    "CS2510": ("CS2100", "Fall 2025"),
    "CS3500": ("CS3100", "Fall 2025"),
}
_PREDECESSORS = {new: (old, since) for old, (new, since) in COURSE_SUCCESSORS.items()}

# Companion sections ("Lab for CS 3100", "Recitation for CS 1800") have their
# own codes in Banner. On a professor's page they repeat the course they
# belong to.
_COMPANION_RE = re.compile(r"^(lab|recitation) for ", re.IGNORECASE)

# The chip is hidden once its row is this old: if the scrape stops, the chip
# vanishes rather than asserting a stale roster through add/drop.
TEACHING_MAX_AGE_DAYS = 21

# Above this many courses the row is a roster artifact, not a teaching load:
# Banner attaches lab coordinators to every section of their programme (three
# physics coordinators each sat on ~150 sections of 9-11 courses in Fall 2026).
# 94% of chips carry 1-3 courses.
TEACHING_MAX_COURSES = 6


def display_name(banner_name):
    """Banner's "Last, First Middle" -> "First Middle Last"."""
    if not banner_name:
        return banner_name
    last, sep, first = banner_name.partition(",")
    return f"{first.strip()} {last.strip()}" if sep and first.strip() else banner_name.strip()


def _terms(joined):
    return [t for t in (joined or "").split(",") if t]


def _whole(value):
    return round(value) if value is not None else None


def _course_link(code, since, query_one):
    """The other end of a successor link. hasPage: a course page exists to
    link to (pages are built from course_catalog, i.e. reviewed courses)."""
    offering = query_one(
        "SELECT course_title FROM banner_course_offerings WHERE subject_course = %s",
        (code,))
    page = query_one("SELECT name FROM course_catalog WHERE code = %s", (code,))
    name = (offering or {}).get("course_title") or (page or {}).get("name")
    return {"code": code, "name": name, "since": since, "hasPage": page is not None}


def course_history(code, query, query_one):
    """A course page's history section, or None when Banner knows nothing."""
    offering = query_one("""
        SELECT subject_course, course_title, last_term_label, pattern,
               fall_years, spring_years, summer_years, pattern_window_years,
               median_section_size, credit_hours, instructor_count, offered_now
        FROM banner_course_offerings WHERE subject_course = %s
    """, (code,))
    successor = COURSE_SUCCESSORS.get(code)
    predecessor = _PREDECESSORS.get(code)
    if not offering and not successor and not predecessor:
        return None

    instructors = query("""
        SELECT bci.instructor_name, bci.professor_slug, pc.name AS catalog_name,
               bci.terms_taught, bci.last_term_label, bci.recent_terms,
               bci.avg_enrollment
        FROM banner_course_instructors bci
        LEFT JOIN professors_catalog pc ON pc.slug = bci.professor_slug
        WHERE bci.subject_course = %s
        ORDER BY bci.last_term_code DESC, bci.terms_taught DESC, bci.instructor_name
    """, (code,)) if offering else []

    o = offering or {}
    return {
        "pattern": o.get("pattern"),
        "seasonYears": {"fall": o.get("fall_years"), "spring": o.get("spring_years"),
                        "summer": o.get("summer_years")} if offering else None,
        "windowYears": o.get("pattern_window_years"),
        "lastOffered": o.get("last_term_label"),
        "offeredNow": _terms(o.get("offered_now")),
        "creditHours": o.get("credit_hours"),
        "typicalClassSize": _whole(o.get("median_section_size")),
        "instructorCount": o.get("instructor_count"),
        "instructors": [{
            "name": r["catalog_name"] or display_name(r["instructor_name"]),
            "slug": r["professor_slug"],
            "termsTaught": r["terms_taught"],
            "lastTerm": r["last_term_label"],
            "recentTerms": _terms(r["recent_terms"]),
            "avgClassSize": _whole(r["avg_enrollment"]),
        } for r in instructors],
        "replacedBy": _course_link(*successor, query_one) if successor else None,
        "replaces": _course_link(*predecessor, query_one) if predecessor else None,
    }


def professor_course_history(slug, query):
    """Every course Banner has this professor teaching since Fall 2021, most
    recently taught first. Labs and recitations are left out."""
    rows = query("""
        SELECT bci.subject_course, bco.course_title, bci.terms_taught,
               bci.last_term_label, bci.recent_terms, bci.avg_enrollment,
               cc.code IS NOT NULL AS has_page
        FROM banner_course_instructors bci
        LEFT JOIN banner_course_offerings bco ON bco.subject_course = bci.subject_course
        LEFT JOIN course_catalog cc ON cc.code = bci.subject_course
        WHERE bci.professor_slug = %s
        ORDER BY bci.last_term_code DESC, bci.terms_taught DESC, bci.subject_course
    """, (slug,))
    return [{
        "code": r["subject_course"],
        "name": r["course_title"],
        "termsTaught": r["terms_taught"],
        "lastTerm": r["last_term_label"],
        "recentTerms": _terms(r["recent_terms"]),
        "avgClassSize": _whole(r["avg_enrollment"]),
        "hasPage": bool(r["has_page"]),
    } for r in rows if not _COMPANION_RE.match(r["course_title"] or "")]


def teaching_now(name_key, query, query_one, now=None):
    """The current-season chip, or None.

    None means "nothing to say", never "not teaching": about a third of
    Banner's instructors have no catalog match, so absence is ignorance.
    """
    row = query_one("""
        SELECT term_desc, course_codes, campuses, scraped_at
        FROM professor_teaching WHERE name_key = %s
        ORDER BY scraped_at DESC LIMIT 1
    """, (name_key,))
    if not row:
        return None

    now = now or datetime.now(timezone.utc)
    scraped_at = row.get("scraped_at")
    if scraped_at is not None:
        if scraped_at.tzinfo is None:
            scraped_at = scraped_at.replace(tzinfo=timezone.utc)
        if now - scraped_at > timedelta(days=TEACHING_MAX_AGE_DAYS):
            return None

    codes = [c for c in (row.get("course_codes") or "").split(",") if c]
    if not codes or len(codes) > TEACHING_MAX_COURSES:
        return None

    pages = {r["code"] for r in query(
        "SELECT code FROM course_catalog WHERE code IN %s", (tuple(codes),))}
    return {
        "termDesc": row.get("term_desc"),
        "courseCodes": codes,
        # Pipe-joined: campus names contain commas ("Oakland, CA").
        "campuses": [c for c in (row.get("campuses") or "").split("|") if c],
        "linkableCodes": [c for c in codes if c in pages],
    }
