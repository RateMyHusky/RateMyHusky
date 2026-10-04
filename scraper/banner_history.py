"""Course and instructor history from stored Banner sections. Pure functions.

Who taught this course, when, and to how many
students — rebuilt from Banner, which keeps every section back to 2009. Two
outputs, each one row per thing a page shows:

  course_instructors   (subject_course, instructor): terms taught, sections,
                       typical class size, campuses, formats. Read by subject
                       for a course page, by slug for a professor page.
  course_offerings     subject_course: when it runs (Fall / Spring / Summer
                       pattern), typical class size, how many people teach it,
                       credit hours, and whether it is on the current schedule.

Scope: what puts a review in context — who taught what, when, and to how big a
room — summarised across terms, plus two basics a course page needs (credits,
offered this term). The rest of what a student reads to register (seats,
waitlists, NUpath, campus and format of the course) is SearchNEU's job, not
ours, and is deliberately absent.

Nothing here touches the network or a database; match_banner_instructors.py
reads the rows and writes the results.
"""

import re
from collections import defaultdict
from statistics import median

from banner_api import (NON_PLACE_CAMPUSES, NON_TEACHING_SCHEDULE_TYPES,
                        pattern_season)

# A coordinator Banner lists on every lab of a programme is not teaching all of
# them. Same threshold and same reasoning as backend/teaching_history.py's TEACHING_MAX_COURSES
# for the live chip (three physics coordinators each sat on ~150 sections of
# 9-11 courses in Fall 2026); here it is applied per term, so a real teaching
# load in other terms is kept.
MAX_COURSES_PER_TERM = 6

# "Usually offered in Fall" is judged over this many academic years. Four is a
# full undergraduate cycle: long enough that an every-other-year course doesn't
# read as annual, short enough that a course dropped in 2019 doesn't.
PATTERN_YEARS = 4
# Offered in at least this share of those years counts as regular.
REGULAR_SHARE = 0.75

SEASON_ORDER = ("Fall", "Spring", "Summer")

# Titles too generic to suggest that one code replaced another. Measured on the
# 2026-10-01 candidates: "Topics", "Projects for Professionals" and the like
# matched across unrelated subjects.
_GENERIC_TITLE_RE = re.compile(
    r"^(special )?topics\b|independent study|directed (study|research)|thesis|"
    r"dissertation|elective|projects for professionals|^research\b|internship|"
    r"co-?op|practicum|continuation|directed reading|^readings?\b|capstone$|seminar$|"
    r"exam preparation",
    re.IGNORECASE)


def academic_year(term_code):
    """Term code -> academic year it belongs to.

    Banner's codes lead with the academic year's ending calendar year: Fall
    2026 is 202710, Spring 2026 is 202630, Summer 2026 is 202650. So Fall and
    the following Spring and Summer share a prefix, which is exactly the
    grouping an offering pattern needs.
    """
    return int(str(term_code)[:4])


def is_teaching(row):
    return (row.get("schedule_type") or "").lower() not in NON_TEACHING_SCHEDULE_TYPES


def is_cancelled(row):
    """A closed-term section with no one enrolled.

    Almost always a cancelled section Banner kept, not an empty classroom, so it
    must not count as taught or offered. Open terms are excluded: 0 enrolled
    there just means registration hasn't filled it yet. An unknown (None)
    headcount is kept.
    """
    return bool(row.get("closed")) and row.get("enrollment") == 0


def roster_artifacts(rows):
    """{(term_code, instructor_key)} listed on too many distinct courses that term."""
    courses = defaultdict(set)
    for r in rows:
        if r.get("instructor_key") and r.get("subject_course") and is_teaching(r):
            courses[(r["term_code"], r["instructor_key"])].add(r["subject_course"])
    return {k for k, v in courses.items() if len(v) > MAX_COURSES_PER_TERM}


def place(campus):
    if campus and campus.strip().lower() not in NON_PLACE_CAMPUSES:
        return campus
    return None


def _avg(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def _size_sample(sections):
    """Closed-term sections with a real headcount.

    Open terms are a mid-registration snapshot, and an enrollment of 0 on a
    closed term is almost always a cancelled section Banner kept, not an empty
    classroom.
    """
    return [s for s in sections if s.get("closed") and (s.get("enrollment") or 0) > 0]


def _labels_newest_first(term_rows):
    """[(term_code, label)] -> labels, newest first, one per label.

    Law and CPS share a label with the main term ("Fall 2025"), so the label is
    the grain students see.
    """
    out, seen = [], set()
    for code, label in sorted(term_rows, key=lambda t: int(t[0]), reverse=True):
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out


def build_course_instructors(rows, match):
    """Section-instructor rows -> one dict per (subject_course, instructor_key).

    `rows` are banner_sections joined to banner_section_instructors and
    banner_terms (one row per section-instructor; TBA sections carry no
    instructor_key and are ignored here). `match(instructor_key, course,
    term_codes)` returns (slug, name_key, method) or (None, None, reason) — the
    same matcher the chip uses, so a professor's history and chip never
    disagree about who they are. It gets the course and terms because a name
    alone isn't identity: the matcher checks the course's subject against the
    professor's department and refuses names that were two people on a
    term's roster. Unmatched instructors are kept with a null slug: a course
    page can still name them.

    Spellings that match the same professor ("Williams, Tom" and "Williams,
    Thomas") are merged into one row per course, as build_rows merges them for
    the chip; the row keeps the newest spelling. Unmatched spellings stay apart.

    Cancelled sections (is_cancelled) are dropped before grouping.
    """
    artifacts = roster_artifacts(rows)
    groups = {}
    for r in rows:
        key = r.get("instructor_key")
        course = r.get("subject_course")
        if not key or not course or not is_teaching(r) or is_cancelled(r):
            continue
        if (r["term_code"], key) in artifacts:
            continue
        g = groups.setdefault((course, key), {
            "name": r.get("instructor_name"), "terms": set(), "crns": set(),
            "sections": [], "campuses": set(), "methods": set(),
            "primary": False,
        })
        g["terms"].add((r["term_code"], r["term_label"]))
        if (r["term_code"], r["crn"]) not in g["crns"]:
            g["crns"].add((r["term_code"], r["crn"]))
            g["sections"].append(r)
        g["primary"] = g["primary"] or bool(r.get("is_primary"))
        if place(r.get("campus")):
            g["campuses"].add(r["campus"])
        if r.get("instructional_method"):
            g["methods"].add(r["instructional_method"])

    merged = {}   # (course, name_key, or the raw key when unmatched) -> group
    for (course, key), g in sorted(groups.items()):
        slug, name_key, method = match(key, course, {c for c, _ in g["terms"]})
        newest = max(int(c) for c, _ in g["terms"])
        m = merged.get((course, name_key or ("unmatched", key)))
        if m is None:
            merged[(course, name_key or ("unmatched", key))] = {
                **g, "key": key, "newest": newest,
                "slug": slug, "name_key": name_key, "method": method}
            continue
        if newest > m["newest"]:
            m.update(key=key, name=g["name"], newest=newest)
        m["terms"] |= g["terms"]
        for sec in g["sections"]:
            if (sec["term_code"], sec["crn"]) not in m["crns"]:
                m["crns"].add((sec["term_code"], sec["crn"]))
                m["sections"].append(sec)
        m["primary"] = m["primary"] or g["primary"]
        m["campuses"] |= g["campuses"]
        m["methods"] |= g["methods"]

    out = []
    for (course, _), g in sorted(merged.items(), key=lambda kv: (kv[0][0], kv[1]["key"])):
        key, slug, name_key, method = g["key"], g["slug"], g["name_key"], g["method"]
        codes = sorted((int(c) for c, _ in g["terms"]))
        labels = _labels_newest_first(g["terms"])
        size = _size_sample(g["sections"])
        out.append({
            "subject_course": course,
            "instructor_key": key,
            "instructor_name": g["name"],
            "professor_slug": slug,
            "name_key": name_key,
            "match_method": method,
            "terms_taught": len(labels),
            "sections": len(g["sections"]),
            "first_term_code": str(codes[0]),
            "last_term_code": str(codes[-1]),
            "last_term_label": labels[0],
            "recent_terms": ",".join(labels[:6]),
            "avg_enrollment": _avg([s["enrollment"] for s in size]),
            "was_primary": g["primary"],
            "campuses": "|".join(sorted(g["campuses"])) or None,
            "methods": "|".join(sorted(g["methods"])) or None,
        })
    return out


def offering_pattern(years_by_season, window):
    """({season: {academic years}}, [academic years]) -> (label, counts).

    The label names every season the course ran in at least REGULAR_SHARE of
    the window's years ("Fall and Spring"). A course that ran inside the window
    but never that regularly is "Irregular"; one that didn't run at all is
    "Not offered recently" (build_course_offerings turns that into "New" for a
    course whose only sections are in the year still in progress). Counts are returned too, so a page can say "Fall
    in 4 of the last 4 years" instead of only the label.
    """
    counts = {s: len(years_by_season.get(s, set()) & set(window)) for s in SEASON_ORDER}
    if not window:
        return "Not offered recently", counts
    regular = [s for s in SEASON_ORDER if counts[s] >= REGULAR_SHARE * len(window)]
    if regular:
        return " and ".join(regular), counts
    if any(counts.values()):
        return "Irregular", counts
    return "Not offered recently", counts


def pattern_window(term_closed, years=PATTERN_YEARS):
    """{term_code: closed} -> the last `years` complete academic years on record.

    An academic year with any open term is in progress (on 2026-10-01, Fall
    2026 is open and alone in its year), so counting it would make every
    Spring course look one year short. Years inside the span that hold no
    stored terms — a backfill that hasn't reached them — are left out rather
    than counted as "not offered", which would understate every course.
    """
    in_progress = {academic_year(c) for c, closed in term_closed.items() if not closed}
    complete = sorted({academic_year(c) for c in term_closed} - in_progress)
    if not complete:
        return []
    last = complete[-1]
    return [y for y in complete if y > last - years]


def _credits(sections):
    """"4", "1-4", or None from the newest section that has credit hours."""
    for s in sorted(sections, key=lambda s: int(s["term_code"]), reverse=True):
        low, high = s.get("credit_hours_low"), s.get("credit_hours_high")
        if low is None:
            continue
        fmt = lambda v: str(int(v)) if float(v).is_integer() else str(v)  # noqa: E731
        return f"{fmt(low)}-{fmt(high)}" if high not in (None, low) else fmt(low)
    return None


def build_course_offerings(sections, instructor_rows=()):
    """banner_sections rows (joined to banner_terms) -> one dict per course.

    `sections` are one row per section, TBA included. `instructor_rows` are
    used only to count distinct instructors, with the same roster-artifact
    filter as build_course_instructors. Cancelled sections (is_cancelled)
    count toward nothing; the pattern window still sees their terms, since a
    term that was stored is a term that was looked at.
    """
    window = pattern_window({s["term_code"]: s.get("closed") for s in sections})

    by_course = defaultdict(list)
    for s in sections:
        if s.get("subject_course") and is_teaching(s) and not is_cancelled(s):
            by_course[s["subject_course"]].append(s)

    artifacts = roster_artifacts(instructor_rows)
    instructors = defaultdict(set)
    for r in instructor_rows:
        if (r.get("instructor_key") and r.get("subject_course") and is_teaching(r)
                and not is_cancelled(r)
                and (r["term_code"], r["instructor_key"]) not in artifacts):
            instructors[r["subject_course"]].add(r["instructor_key"])

    out = []
    for course, secs in sorted(by_course.items()):
        newest = max(secs, key=lambda s: int(s["term_code"]))
        terms = {(s["term_code"], s["term_label"]) for s in secs}
        labels = _labels_newest_first(terms)
        years_by_season = defaultdict(set)
        sections_per_label = defaultdict(int)
        for s in secs:
            years_by_season[pattern_season(s["season_group"])].add(academic_year(s["term_code"]))
            sections_per_label[s["term_label"]] += 1
        label, counts = offering_pattern(years_by_season, window)
        if label == "Not offered recently" and any(not s.get("closed") for s in secs):
            label = "New"     # first runs in the year still in progress

        size = _size_sample(secs)
        open_labels = sorted({s["term_label"] for s in secs if not s.get("closed")})

        out.append({
            "subject_course": course,
            "subject": newest.get("subject"),
            "course_title": newest.get("course_title"),
            "first_term_code": str(min(int(s["term_code"]) for s in secs)),
            "last_term_code": str(int(newest["term_code"])),
            "last_term_label": labels[0],
            "terms_offered": len(labels),
            "pattern": label,
            "fall_years": counts["Fall"],
            "spring_years": counts["Spring"],
            "summer_years": counts["Summer"],
            "pattern_window_years": len(window),
            "avg_sections_per_term": round(len(secs) / len(labels), 1),
            "avg_section_size": _avg([s["enrollment"] for s in size]),
            "median_section_size": median([s["enrollment"] for s in size]) if size else None,
            "credit_hours": _credits(secs),
            "instructor_count": len(instructors.get(course, ())),
            "offered_now": ",".join(open_labels) or None,
        })
    return out


def _title_key(title):
    t = (title or "").lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]", "", t)


def rename_candidates(offerings, course_instructors):
    """Pairs (old code, new code) that look like one course renumbered.

    Banner never says "formerly X", so this only proposes; a person approves
    each pair into COURSE_RENAMES (match_banner_instructors.py). A candidate
    needs all of:
      - the same title, after case and punctuation are ignored
      - a title specific enough to mean something (not "Topics")
      - the old code's last term strictly before the new code's first, which
        also rules out cross-listings: those run in the same term
      - at least one instructor who taught both
    Measured 2026-10-01 on Banner: 78 of 769 retired codes reappeared
    under a new code with the same title, a mix of real renumbers
    (ECON1291 -> ECON3291), subject renames (AFAM -> AFCS) and false matches
    the instructor requirement removes.
    """
    people = defaultdict(dict)
    for r in course_instructors:
        people[r["subject_course"]][r["instructor_key"]] = r["instructor_name"]
    by_title = defaultdict(list)
    for o in offerings:
        title = o.get("course_title") or ""
        if title and not _GENERIC_TITLE_RE.search(title):
            by_title[_title_key(title)].append(o)

    out = []
    for group in by_title.values():
        for old in group:
            for new in group:
                if old is new or int(old["last_term_code"]) >= int(new["first_term_code"]):
                    continue
                shared = set(people[old["subject_course"]]) & set(people[new["subject_course"]])
                if not shared:
                    continue
                out.append({
                    "old_code": old["subject_course"],
                    "new_code": new["subject_course"],
                    "title": new["course_title"],
                    "old_last_term": old["last_term_label"],
                    "new_first_term_code": new["first_term_code"],
                    "same_subject": old["subject"] == new["subject"],
                    "shared_instructors": "|".join(sorted(
                        people[new["subject_course"]][k] for k in shared)),
                })
    return sorted(out, key=lambda c: (c["old_code"], c["new_code"]))
