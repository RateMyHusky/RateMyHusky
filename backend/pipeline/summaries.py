"""Per-source summary rows from stored RMP data (spec §5.3.3).

Three row kinds: professor (slug, ''), course ('', code), professor x course
(slug, code). Rating and count come from the stored reviews, so the
distribution adds up to the count; would-take-again and difficulty are RMP's
own page values, rating-count-weighted across a professor's pages. A professor
with no usable stored rating falls back to the page-weighted RMP rating.
"""

import rmp

from .rmp_fields import rmp_difficulty, rmp_wta

EMPTY_DISTRIBUTION = {str(s): 0 for s in range(1, 6)}


def _mean(values):
    return round(sum(values) / len(values), 2) if values else None


def _weighted(pairs):
    pairs = [(v, w) for v, w in pairs if v is not None and w]
    total = sum(w for _, w in pairs)
    return round(sum(v * w for v, w in pairs) / total, 2) if total else None


def _row(slug, code, reviews):
    return {
        "professor_slug": slug, "course_code": code, "source": "rmp",
        "rating": _mean([r["quality"] for r in reviews if r["quality"] and 1 <= r["quality"] <= 5]),
        "difficulty": _mean([r["difficulty"] for r in reviews if r["difficulty"] and 1 <= r["difficulty"] <= 5]),
        "would_take_again_pct": None,
        "num_ratings": len(reviews),
        "num_comments": sum(1 for r in reviews if (r["comment"] or "").strip()),
        "hours_per_week": None,
        "rating_distribution": rmp.rating_distribution(reviews) if reviews else dict(EMPTY_DISTRIBUTION),
        "grade_distribution": rmp.grade_distribution(reviews),
    }


def build_summaries(pages, reviews, page_slug, name_key_slug, linked_slugs):
    """(rows, coverage). Pure."""
    coverage = dict.fromkeys(("reviews", "via_page", "via_name_key", "unmapped", "name_key_alone"), 0)
    coverage["reviews"] = len(reviews)
    by_slug, by_code, by_pair = {}, {}, {}
    for r in reviews:
        if r.get("name_key") in name_key_slug:
            coverage["name_key_alone"] += 1
        slug = page_slug.get((r["professor_name"], r["department"]))
        if slug:
            coverage["via_page"] += 1
        else:
            slug = name_key_slug.get(r.get("name_key"))
            if not slug:
                coverage["unmapped"] += 1
                continue
            coverage["via_name_key"] += 1
        by_slug.setdefault(slug, []).append(r)
        if r["course_code"]:
            by_code.setdefault(r["course_code"], []).append(r)
            by_pair.setdefault((slug, r["course_code"]), []).append(r)

    pages_by_slug = {}
    for p in pages:
        pages_by_slug.setdefault(p["slug"], []).append(p)

    rows = []
    for slug in sorted(set(linked_slugs)):
        row = _row(slug, "", by_slug.get(slug, []))
        ps = pages_by_slug.get(slug, [])
        weight = [(p["num_ratings"] or 0) for p in ps]
        row["would_take_again_pct"] = _weighted(zip([rmp_wta(p["would_take_again_pct"]) for p in ps], weight))
        page_difficulty = _weighted(zip([rmp_difficulty(p["level_of_difficulty"]) for p in ps], weight))
        row["difficulty"] = page_difficulty if page_difficulty is not None else row["difficulty"]
        if row["rating"] is None:
            row["rating"] = _weighted(zip([p["rating"] if p["rating"] else None for p in ps], weight))
        rows.append(row)
    rows += [_row("", code, rs) for code, rs in sorted(by_code.items())]
    rows += [_row(slug, code, rs) for (slug, code), rs in sorted(by_pair.items())]
    return rows, coverage
