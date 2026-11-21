"""Injectable SQL and validation for student profiles (grad year, majors, minors).

Same pattern as bookmarks.py: pure functions taking `query_one` / `write`;
server.py owns HTTP and auth.
"""

import re

from bookmarks import item_exists
from programs import MAJORS, MINORS, OTHER

MAX_PROGRAMS = 4  # cap on majors and, separately, on minors
MAX_VISIBLE_SECONDS = 1800  # a tab left open overnight counts as 30 minutes
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
    """Returns (clean, None) with {"level", "grad_year", "majors", "minors"}, or (None, error).

    A null gradYear means grad student (level "grad"): no majors or minors. Otherwise
    the level is "undergrad", the year must be last year through five years out and at least one major is required."""
    if "gradYear" not in data:
        return None, "gradYear is required"
    year = data["gradYear"]
    majors = _programs(data.get("majors", []), MAJORS)
    minors = _programs(data.get("minors", []), MINORS)
    if majors is None or minors is None:
        return None, "majors and minors must be lists of known programs, at most 4 each"
    if year is None:
        if majors or minors:
            return None, "Grad students have no majors or minors"
        return {"level": "grad", "grad_year": None, "majors": [], "minors": []}, None
    if type(year) is not int or not this_year - 1 <= year <= this_year + 5:
        return None, "gradYear is out of range"
    if not majors:
        return None, "At least one major is required"
    return {"level": "undergrad", "grad_year": year, "majors": majors, "minors": minors}, None


def profile_status(viewer_hash, query_one):
    row = query_one("SELECT tracking_opt_out FROM student_profiles WHERE viewer_hash = %s", (viewer_hash,))
    return {"exists": row is not None, "optedOut": bool(row and row["tracking_opt_out"])}


def rater_profile(viewer_hash, query_one):
    """(level, grad_year) to copy onto a rating: ("undergrad", year), ("grad", None), or
    (None, None) for no signed-in student, no profile, opted out, or the opted-out stub row (no level)."""
    if viewer_hash is None:
        return None, None
    row = query_one("SELECT level, grad_year, tracking_opt_out FROM student_profiles WHERE viewer_hash = %s", (viewer_hash,))
    if row is None or row["tracking_opt_out"] or row["level"] is None:
        return None, None
    return row["level"], row["grad_year"]


def save_profile(viewer_hash, clean, write):
    write(
        "INSERT INTO student_profiles (viewer_hash, level, grad_year, majors, minors) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (viewer_hash) DO UPDATE SET level = EXCLUDED.level, grad_year = EXCLUDED.grad_year, "
        "majors = EXCLUDED.majors, minors = EXCLUDED.minors, updated_at = now()",
        (viewer_hash, clean["level"], clean["grad_year"], clean["majors"], clean["minors"]),
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


def record_view(viewer_hash, view, query_one, write):
    """Stores one page view. Returns "ignored" (no profile or opted out: nothing
    else is queried or written), "not_found" (item not in the catalog), or "ok".

    A course filter is kept only on professor views and only if it is a real course code.
    viewer_hash is rating_identity.keyed_hash(secret, "viewer", sub): it keys both the profile and the view row, the raw sub is never stored.

    The profile check is repeated inside the INSERT with FOR SHARE: that row lock makes the
    insert wait for, or be refused by, a concurrent opt-out, so a view can't land after the
    opt-out has deleted that student's views. The early check above just skips the item lookups."""
    profile = profile_status(viewer_hash, query_one)
    if not profile["exists"] or profile["optedOut"]:
        return "ignored"
    if not item_exists(view["item_type"], view["item_key"], query_one):
        return "not_found"
    course_filter = view["course_filter"]
    if view["item_type"] != "professor" or not (course_filter and item_exists("course", course_filter, query_one)):
        course_filter = None
    write(
        "INSERT INTO page_views (viewer_hash, item_type, item_key, visible_seconds, reached_section, course_filter) "
        "SELECT %s, %s, %s, %s, %s, %s WHERE EXISTS "
        "(SELECT 1 FROM student_profiles WHERE viewer_hash = %s AND NOT tracking_opt_out FOR SHARE)",
        (viewer_hash, view["item_type"], view["item_key"], view["visible_seconds"], view["reached_section"],
         course_filter, viewer_hash),
    )
    return "ok"
