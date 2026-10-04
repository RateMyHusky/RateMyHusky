"""The 'blend' row per entity: every source combined (spec §5.3.4).

Rating-like values are means weighted by each source's rating count times its
weight; counts and distributions are summed. With RMP alone, blend == RMP.
"""

SOURCE_WEIGHTS = {"rmp": 1.0}

_AVERAGED = ("rating", "difficulty", "would_take_again_pct", "hours_per_week")
_DISTRIBUTIONS = ("rating_distribution", "grade_distribution")


def _wmean(rows, key):
    present = [r for r in rows if r[key] is not None]
    if not present:
        return None
    weights = [r["num_ratings"] * SOURCE_WEIGHTS.get(r["source"], 1.0) for r in present]
    total = sum(weights)
    if not total:  # a value with no rating count behind it (e.g. RMP page rating, no stored reviews)
        return round(sum(r[key] for r in present) / len(present), 2)
    return round(sum(r[key] * w for r, w in zip(present, weights)) / total, 2)


def _sum(rows, key):
    out = {}
    for r in rows:
        for k, v in (r[key] or {}).items():
            out[k] = out.get(k, 0) + v
    return out


def blend(rows):
    groups = {}
    for r in rows:
        groups.setdefault((r["professor_slug"], r["course_code"]), []).append(r)
    out = []
    for (slug, code), rs in sorted(groups.items()):
        b = {"professor_slug": slug, "course_code": code, "source": "blend",
             "num_ratings": sum(r["num_ratings"] for r in rs),
             "num_comments": sum(r["num_comments"] for r in rs)}
        b.update({k: _wmean(rs, k) for k in _AVERAGED})
        b.update({k: _sum(rs, k) for k in _DISTRIBUTIONS})
        out.append(b)
    return out
