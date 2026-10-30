import pytest

from pipeline.read_models import (catalog_rows, course_rows, course_search_text, drop_denied, keep_summaries,
                                  retired_courses, stats, verify)
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


def test_banner_professor_without_a_link_is_in_the_catalog_with_no_url():
    [row] = catalog_rows([{**PROF, "origin": "banner"}], [], [], [], is_denied=lambda k: False)
    assert row["professor_url"] is None
    assert (row["num_ratings"], row["total_reviews"], row["avg_rating"]) == (0, 0, None)


def test_survey_professor_without_a_link_is_in_the_catalog_with_no_url():
    [row] = catalog_rows([{**PROF, "origin": "survey"}], [], [], [], is_denied=lambda k: False)
    assert row["professor_url"] is None


def test_rmp_professor_without_a_link_stays_out_of_the_catalog():
    assert catalog_rows([{**PROF, "origin": "rmp"}], [], [], [], is_denied=lambda k: False) == []
    assert catalog_rows([PROF], [], [], [], is_denied=lambda k: False) == []   # a roster row this run


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
    assert rows["CS3500"]["search_text"] == "cs3500 object-oriented design cs 3500"


@pytest.mark.parametrize("code, text, expected", [
    ("CS3500", "cs3500 object-oriented design", "cs3500 object-oriented design cs 3500"),
    ("CS3500", "cs3500 cs 3500 ood", "cs3500 cs 3500 ood"),  # already spaced: not added twice
    ("CS3500", None, "cs 3500"),
    ("WEIRD-1", "weird-1 thing", "weird-1 thing"),         # not letters then digits: left as is
])
def test_course_search_text_holds_the_spaced_code(code, text, expected):
    assert course_search_text(code, text) == expected


def test_keep_summaries_drops_rows_for_professors_outside_the_catalog():
    kept = keep_summaries(SUMMARIES + [srow("gone", "", "rmp")], {"olin-guha"})
    assert {r["professor_slug"] for r in kept} == {"olin-guha", ""}


def test_verify_floors():
    catalog = [{"slug": f"p{i}", "department": "CS", "total_comments": 1, "professor_url": "u", "num_ratings": 0}
               for i in range(3000)]
    courses = [{"code": f"C{i}"} for i in range(5000)]
    assert verify(catalog, courses) == []
    assert verify(catalog[:10], courses)                             # too few professors
    assert verify(catalog, courses[:10])                             # too few courses


def test_verify_fails_when_no_professor_is_linked_or_rated():
    catalog = [{"slug": f"p{i}", "department": "CS", "total_comments": 0, "professor_url": None, "num_ratings": 0}
               for i in range(5000)]
    assert verify(catalog, [{"code": f"C{i}"} for i in range(5000)])


def test_stats():
    catalog = [{"slug": "a", "department": "CS", "total_comments": 3, "professor_url": "u", "num_ratings": 0},
               {"slug": "b", "department": "Law", "total_comments": 2, "professor_url": None, "num_ratings": 4}]
    assert stats(catalog, [{"code": "X"}], []) == {"professors": 2, "courses": 1,
                                                   "comments": 5, "departments": 2}


def test_stats_ignore_unrated_unlinked_professors():
    catalog = [{"slug": "a", "department": "CS", "total_comments": 0, "professor_url": "u", "num_ratings": 0},
               {"slug": "b", "department": "Biology", "total_comments": 0, "professor_url": None, "num_ratings": 0}]
    counts = stats(catalog, [], [])
    assert (counts["professors"], counts["departments"]) == (1, 1)


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


def test_college_override_replaces_the_stored_college():
    [row] = catalog_rows([PROF], LINKS, PAGES, SUMMARIES, is_denied=lambda k: False,
                         colleges={"olin-guha": "Law"})
    assert row["college"] == "Law"
    [row] = catalog_rows([PROF], LINKS, PAGES, SUMMARIES, is_denied=lambda k: False,
                         colleges={"someone-else": "Law"})
    assert row["college"] == "Khoury"


def test_retired_courses_take_the_successors_department_and_banners_title():
    cat = [{"code": "CS2000", "name": "Intro to Program Design", "department": "Computer Science",
            "subject": "CS", "search_text": "cs2000", "is_placeholder": False}]
    [row] = retired_courses(cat, {"CS2500": "Fundamentals of  Computer Science 1"})
    assert row == {"code": "CS2500", "name": "Fundamentals of Computer Science 1",
                   "department": "Computer Science", "subject": "CS",
                   "search_text": "cs2500 fundamentals of computer science 1", "is_placeholder": False}


def test_retired_courses_skip_codes_the_catalog_still_lists_or_banner_never_titled():
    succ = {"code": "CS2000", "name": "x", "department": "CS", "subject": "CS", "search_text": "", "is_placeholder": False}
    still = {**succ, "code": "CS2500"}
    assert retired_courses([succ, still], {"CS2500": "Fundies 1"}) == []
    assert retired_courses([succ], {}) == []
    assert retired_courses([], {"CS2500": "Fundies 1"}) == []      # no successor row to copy from
