from pipeline.read_models import catalog_rows, course_rows, drop_denied, keep_summaries, stats, verify
from pipeline.summaries import build_summaries

PROF = {"slug": "olin-guha", "name": "Olin Guha", "name_key": "olin guha", "department": "CS",
        "college": "Khoury", "image_url": "https://img/o.jpg", "focus_x": 40.0, "focus_y": 20.0}
LINKS = [{"rmp_id": 1, "slug": "olin-guha", "professor_url": "u1"},
         {"rmp_id": 2, "slug": "olin-guha", "professor_url": "u2"}]
PAGES = [{"rmp_id": 1, "num_ratings": 3}, {"rmp_id": 2, "num_ratings": 40}]


def srow(slug, code, source, rating=4.2, n=12, comments=5, diff=3.1, wta=80.0):
    return {"professor_slug": slug, "course_code": code, "source": source, "rating": rating,
            "difficulty": diff, "would_take_again_pct": wta, "num_ratings": n, "num_comments": comments,
            "hours_per_week": None, "rating_distribution": {}, "grade_distribution": {}}


SUMMARIES = [srow("olin-guha", "", "rmp"), srow("olin-guha", "", "blend"),
             srow("", "CS3500", "rmp", rating=3.9, n=7), srow("", "CS3500", "blend", rating=3.9, n=7)]


def test_catalog_row_columns_and_sources():
    [row] = catalog_rows([PROF], LINKS, PAGES, SUMMARIES, is_denied=lambda k: False)
    assert set(row) == {"slug", "name", "name_key", "department", "college", "avg_rating", "rmp_rating",
                        "num_ratings", "total_reviews", "would_take_again_pct", "difficulty",
                        "professor_url", "image_url", "focus_x", "focus_y", "total_comments"}
    assert row["professor_url"] == "u2"                      # the page with the most ratings
    assert (row["avg_rating"], row["rmp_rating"], row["total_reviews"], row["total_comments"]) == (4.2, 4.2, 12, 5)
    assert (row["name"], row["image_url"]) == ("Olin Guha", "https://img/o.jpg")   # frozen identity


def test_professor_without_a_link_is_not_in_the_catalog():
    assert catalog_rows([PROF], [], [], SUMMARIES, is_denied=lambda k: False) == []


def test_read_models_drop_denied():
    assert catalog_rows([PROF], LINKS, PAGES, SUMMARIES, is_denied=lambda k: k == "olin guha") == []


def test_course_rows_come_from_the_catalog_with_blend_ratings():
    catalog = [{"code": "CS3500", "name": "Object-Oriented Design", "department": "CS",
                "subject": "CS", "search_text": "cs3500 object-oriented design"},
               {"code": "CS2500", "name": "Fundamentals", "department": "CS",
                "subject": "CS", "search_text": "cs2500 fundamentals"}]
    rows = {r["code"]: r for r in course_rows(catalog, SUMMARIES)}
    assert (rows["CS3500"]["avg_rating"], rows["CS3500"]["num_ratings"]) == (3.9, 7)
    assert (rows["CS2500"]["avg_rating"], rows["CS2500"]["num_ratings"]) == (None, 0)
    assert set(rows["CS3500"]) == {"code", "name", "department", "subject", "search_text",
                                   "avg_rating", "difficulty", "num_ratings"}


def test_keep_summaries_drops_rows_for_professors_outside_the_catalog():
    kept = keep_summaries(SUMMARIES + [srow("gone", "", "rmp")], {"olin-guha"})
    assert {r["professor_slug"] for r in kept} == {"olin-guha", ""}


def test_verify_floors():
    catalog = [{"slug": f"p{i}", "department": "CS", "total_comments": 1} for i in range(3000)]
    courses = [{"code": f"C{i}"} for i in range(5000)]
    assert verify(catalog, courses) == []
    assert verify(catalog[:10], courses)                             # too few professors
    assert verify(catalog, courses[:10])                             # too few courses


def test_stats():
    catalog = [{"slug": "a", "department": "CS", "total_comments": 3},
               {"slug": "b", "department": "Law", "total_comments": 2}]
    assert stats(catalog, [{"code": "X"}], []) == {"professors": 2, "courses": 1,
                                                   "comments": 5, "departments": 2}


def test_drop_denied_removes_the_professor_and_their_links_only():
    other = {"slug": "ann-lee", "name": "Ann Lee", "name_key": "ann lee"}
    links = LINKS + [{"rmp_id": 3, "slug": "ann-lee", "professor_url": "u3"}]
    profs, kept = drop_denied([PROF, other], links, is_denied=lambda k: k == "olin guha")
    assert profs == [other]
    assert kept == [links[2]]


def test_denied_professors_review_does_not_reach_the_course_row():
    other = {"slug": "ann-lee", "name": "Ann Lee", "name_key": "ann lee"}
    links = [{"rmp_id": 1, "slug": "olin-guha", "professor_url": "u1"},
             {"rmp_id": 3, "slug": "ann-lee", "professor_url": "u3"}]
    profs, links = drop_denied([PROF, other], links, is_denied=lambda k: k == "olin guha")
    slug_by_id = {l["rmp_id"]: l["slug"] for l in links}
    name_key_slug = {p["name_key"]: p["slug"] for p in profs}

    def rev(rid, name, key):
        return {"id": rid, "professor_name": name, "department": "CS", "name_key": key,
                "course_code": "CS3500", "quality": 5, "difficulty": 3, "grade": "A", "comment": "ok"}

    rows, _ = build_summaries([], [rev(1, "Olin Guha", "olin guha"), rev(2, "Ann Lee", "ann lee")],
                              {}, name_key_slug, set(slug_by_id.values()))
    [course] = [r for r in rows if r["professor_slug"] == "" and r["course_code"] == "CS3500"]
    assert course["num_ratings"] == 1


def test_placeholder_courses_are_kept_only_when_rated():
    catalog = [{"code": "CS3500", "name": "Rated", "department": "CS", "subject": "CS",
                "search_text": "x", "is_placeholder": True},
               {"code": "CS9999", "name": "Unrated", "department": "CS", "subject": "CS",
                "search_text": "y", "is_placeholder": True}]
    assert [r["code"] for r in course_rows(catalog, SUMMARIES)] == ["CS3500"]
