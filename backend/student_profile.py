"""Injectable SQL and validation for student profiles (grad year, majors, minors).

Same pattern as bookmarks.py: pure functions taking `query_one` / `write`;
server.py owns HTTP and auth.
"""

import re

from bookmarks import item_exists
from programs import MAJORS, MINORS, OTHER

MAX_PROGRAMS = 4  # cap on majors and, separately, on minors
MAX_VISIBLE_SECONDS = 7200  # a tab left open overnight counts as two hours
MAX_ITEM_KEY = 200


def _programs(value, allowed):
    """Stripped, de-duplicated names from a list, or None if invalid."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    names = list(dict.fromkeys(v.strip() for v in value))
    if len(names) > MAX_PROGRAMS or any(n not in allowed and n != OTHER for n in names):
        return None
    return names


def validate_profile(data, this_year):
    """Returns (clean, None) with {"grad_year", "majors", "minors"}, or (None, error).

    A null gradYear means grad student: no majors or minors. Otherwise the year
    must be last year through five years out and at least one major is required."""
    if "gradYear" not in data:
        return None, "gradYear is required"
    year = data["gradYear"]
    majors = _programs(data.get("majors"), MAJORS)
    minors = _programs(data.get("minors"), MINORS)
    if majors is None or minors is None:
        return None, "majors and minors must be lists of known programs, at most 4 each"
    if year is None:
        if majors or minors:
            return None, "Grad students have no majors or minors"
        return {"grad_year": None, "majors": [], "minors": []}, None
    if type(year) is not int or not this_year - 1 <= year <= this_year + 5:
        return None, "gradYear is out of range"
    if not majors:
        return None, "At least one major is required"
    return {"grad_year": year, "majors": majors, "minors": minors}, None


def profile_status(user_sub, query_one):
    row = query_one("SELECT tracking_opt_out FROM student_profiles WHERE user_sub = %s", (user_sub,))
    return {"exists": row is not None, "optedOut": bool(row and row["tracking_opt_out"])}


def save_profile(user_sub, clean, write):
    write(
        "INSERT INTO student_profiles (user_sub, grad_year, majors, minors) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (user_sub) DO UPDATE SET grad_year = EXCLUDED.grad_year, "
        "majors = EXCLUDED.majors, minors = EXCLUDED.minors, updated_at = now()",
        (user_sub, clean["grad_year"], clean["majors"], clean["minors"]),
    )


def validate_view(data):
    """Returns (clean, None) with {"item_type", "item_key", "visible_seconds",
    "reached_section", "course_filter"}, or (None, error).

    A junk courseFilter is normalized or dropped, never an error."""
    item_type, item_key = data.get("itemType"), data.get("itemKey")
    seconds, reached = data.get("visibleSeconds"), data.get("reachedSection")
    if item_type not in ("professor", "course"):
        return None, "itemType must be 'professor' or 'course'"
    if not isinstance(item_key, str) or not 1 <= len(item_key) <= MAX_ITEM_KEY:
        return None, "itemKey is required, at most 200 characters"
    if type(seconds) is not int or seconds < 0:
        return None, "visibleSeconds must be a non-negative integer"
    if type(reached) is not bool:
        return None, "reachedSection must be a boolean"
    course_filter = data.get("courseFilter")
    if isinstance(course_filter, str):
        course_filter = re.sub(r"\s+", "", course_filter).upper() or None
    else:
        course_filter = None
    return {"item_type": item_type, "item_key": item_key, "visible_seconds": min(seconds, MAX_VISIBLE_SECONDS),
            "reached_section": reached, "course_filter": course_filter}, None


def record_view(user_sub, view, query_one, write):
    """Stores one page view. Returns "ignored" (no profile or opted out: nothing
    else is queried or written), "not_found" (item not in the catalog), or "ok".

    A course filter is kept only on professor views and only if it is a real course code."""
    profile = profile_status(user_sub, query_one)
    if not profile["exists"] or profile["optedOut"]:
        return "ignored"
    if not item_exists(view["item_type"], view["item_key"], query_one):
        return "not_found"
    course_filter = view["course_filter"]
    if view["item_type"] != "professor" or not (course_filter and item_exists("course", course_filter, query_one)):
        course_filter = None
    write(
        "INSERT INTO page_views (user_sub, item_type, item_key, visible_seconds, reached_section, course_filter) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (user_sub, view["item_type"], view["item_key"], view["visible_seconds"], view["reached_section"], course_filter),
    )
    return "ok"
