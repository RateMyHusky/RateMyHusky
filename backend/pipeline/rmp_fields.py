"""Parsers for fields scraped from Rate My Professors."""

import re


def rmp_id(url):
    """RMP's numeric professor id from a /professor/<id> URL, or None."""
    m = re.search(r"/professor/(\d+)", str(url or ""))
    return int(m.group(1)) if m else None


def rmp_wta(raw):
    """Would-take-again % from RMP's "83%" / "N/A" / -1 field, or None."""
    s = str(raw if raw is not None else "").strip().replace("%", "")
    if not s or s.lower() in ("nan", "n/a"):
        return None
    try:
        wta = round(float(s), 1)
    except (ValueError, TypeError):
        return None
    return None if wta < 0 else wta


def rmp_difficulty(raw):
    """RMP's level_of_difficulty as a 1-5 float, or None (0 means unset)."""
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return None
    return round(val, 2) if val == val and val > 0 else None   # val == val drops NaN
