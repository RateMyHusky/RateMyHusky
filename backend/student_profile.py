"""Injectable SQL and validation for student profiles (grad year, majors, minors).

Same pattern as bookmarks.py: pure functions taking `query_one` / `write`;
server.py owns HTTP and auth.
"""

from programs import MAJORS, MINORS, OTHER

MAX_PROGRAMS = 4  # cap on majors and, separately, on minors


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
