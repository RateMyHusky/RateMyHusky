"""Candidate real codes for a mistyped course code: every valid code one edit away
(substitution, insertion, deletion, adjacent swap) or the same number and suffix
under a known subject variant, kept to the ones Banner knows."""

import re

from rating_checks import COURSE_CODE_RE

# Subjects students type that Banner spells differently, seeded from what RMP
# ratings actually use.
SUBJECT_VARIANTS = {
    "BIO": "BIOL", "ACC": "ACCT", "FIN": "FINA", "PSY": "PSYC",
    "CIV": "CIVE", "ECN": "ECON", "CALC": "MATH",
}
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
MAX_CANDIDATES = 5
_PARTS_RE = re.compile(r"^([A-Z]+)(\d{4}[A-Z]?)$", re.ASCII)


def neighbors(code):
    """Valid codes one edit from `code`, or `code` under its subject variant."""
    splits = [(code[:i], code[i:]) for i in range(len(code) + 1)]
    found = {a + b[1:] for a, b in splits if b}
    found |= {a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1}
    found |= {a + c + b[1:] for a, b in splits if b for c in ALPHABET}
    found |= {a + c + b for a, b in splits for c in ALPHABET}
    parts = _PARTS_RE.match(code)
    if parts and parts.group(1) in SUBJECT_VARIANTS:
        found.add(SUBJECT_VARIANTS[parts.group(1)] + parts.group(2))
    return {c for c in found if c != code and COURSE_CODE_RE.fullmatch(c)}


def taught_candidates(code, slugs, query):
    """{slug: sorted candidates that professor taught per Banner}, one query."""
    rows = query(
        "SELECT DISTINCT professor_slug, subject_course FROM banner_course_instructors "
        "WHERE subject_course = ANY(%s) AND professor_slug = ANY(%s)",
        (sorted(neighbors(code)), list(slugs)),
    )
    found = {slug: [] for slug in slugs}
    for row in rows:
        found[row["professor_slug"]].append(row["subject_course"])
    return {slug: sorted(codes) for slug, codes in found.items()}


def banner_candidates(code, query, slug=None):
    """Up to five {"code", "name"} near matches: the professor's own Banner
    courses when `slug` has any, else every Banner course."""
    names = ("COALESCE(MAX(o.course_title), MAX(c.name)) AS name "
             "FROM banner_course_offerings o LEFT JOIN course_catalog c ON c.code = o.subject_course ")
    params = [sorted(neighbors(code))]
    rows = []
    if slug:
        rows = query(
            "SELECT o.subject_course AS code, " + names +
            "WHERE o.subject_course = ANY(%s) AND o.subject_course IN "
            "(SELECT subject_course FROM banner_course_instructors WHERE professor_slug = %s) "
            "GROUP BY o.subject_course", (params[0], slug))
    if not rows:
        rows = query(
            "SELECT o.subject_course AS code, " + names +
            "WHERE o.subject_course = ANY(%s) GROUP BY o.subject_course", (params[0],))
    return [{"code": r["code"], "name": r["name"]}
            for r in sorted(rows, key=lambda r: r["code"])[:MAX_CANDIDATES]]
