"""The course page payload: /api/courses/<code> and render.py.

Two statements: the course (catalog details and NUpath in one row), then every
source_summary row for the code, with professor names and photos joined on.
"""

import rmp


def build_catalog(course):
    return {"description": course["description"], "credits": course["credit_hours"],
            "prerequisites": course["prerequisites"], "corequisites": course["corequisites"],
            "nupath": list(course["nupath"] or [])}


def build_course(code, query, query_one):
    course = query_one("""
        SELECT cc.code, cc.name, cc.department, k.description, k.credit_hours,
               k.prerequisites, k.corequisites,
               (SELECT array_agg(n.attribute ORDER BY n.attribute)
                FROM catalog_nupath n WHERE n.code = cc.code) AS nupath
        FROM course_catalog cc
        LEFT JOIN catalog_courses k ON k.code = cc.code
        WHERE cc.code = %s
    """, (code,))
    if not course:
        return None
    rows = query("""
        SELECT s.professor_slug, s.source, s.rating, s.difficulty, s.num_ratings,
               s.hours_per_week, p.name, p.image_url, p.focus_x, p.focus_y
        FROM source_summary s
        LEFT JOIN professors_catalog p ON p.slug = s.professor_slug
        WHERE s.course_code = %s
    """, (code,))
    own = {r["source"]: r for r in rows if r["professor_slug"] == ""}
    b = own.get("blend") or {}
    professors = [{
        "slug": r["professor_slug"], "name": r["name"], "imageUrl": r["image_url"],
        "focusX": r["focus_x"] if r["focus_x"] is not None else 50.0,
        "focusY": r["focus_y"] if r["focus_y"] is not None else 30.0,
        "rating": rmp.stat(r["rating"], 2), "difficulty": rmp.stat(r["difficulty"], 2),
        "numRatings": int(r["num_ratings"] or 0),
    } for r in rows if r["professor_slug"] and r["source"] == "blend" and r["name"] is not None]
    professors.sort(key=lambda p: (-p["numRatings"], p["name"]))
    return {
        "code": course["code"], "name": course["name"], "department": course["department"] or "",
        "catalog": build_catalog(course),
        "summary": {
            "rating": rmp.stat(b.get("rating"), 2), "difficulty": rmp.stat(b.get("difficulty"), 2),
            "numRatings": int(b.get("num_ratings") or 0), "hoursPerWeek": rmp.stat(b.get("hours_per_week"), 1),
            "bySource": {src: {"rating": rmp.stat(r["rating"], 2), "numRatings": int(r["num_ratings"] or 0)}
                         for src, r in own.items() if src != "blend"},
        },
        "professors": professors,
    }
