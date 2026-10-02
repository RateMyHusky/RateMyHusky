from pipeline.summaries import build_summaries


def review(rid, name="Olin Guha", dept="CS", code="CS3500", q=5, d=3, grade="A", comment="ok", key="olin guha"):
    return {"id": rid, "professor_name": name, "department": dept, "name_key": key,
            "course_code": code, "quality": q, "difficulty": d, "grade": grade, "comment": comment}


PAGES = [{"slug": "olin-guha", "name": "Olin Guha", "department": "CS", "rating": 4.0,
          "num_ratings": 10, "would_take_again_pct": "80%", "level_of_difficulty": 3.0}]
PAGE_SLUG = {("Olin Guha", "CS"): "olin-guha"}


def rows_by(rows):
    return {(r["professor_slug"], r["course_code"]): r for r in rows}


def test_row_has_exactly_the_table_columns():
    rows, _ = build_summaries(PAGES, [review(1)], PAGE_SLUG, {}, ["olin-guha"])
    assert all(set(r) == {"professor_slug", "course_code", "source", "rating", "difficulty",
                          "would_take_again_pct", "num_ratings", "num_comments", "hours_per_week",
                          "rating_distribution", "grade_distribution"} for r in rows)
    assert {r["source"] for r in rows} == {"rmp"}


def test_professor_level_uses_stored_reviews_for_rating_and_count():
    rows, _ = build_summaries(PAGES, [review(1, q=5), review(2, q=3, comment="")], PAGE_SLUG, {}, ["olin-guha"])
    p = rows_by(rows)[("olin-guha", "")]
    assert (p["rating"], p["num_ratings"], p["num_comments"]) == (4.0, 2, 1)
    assert p["would_take_again_pct"] == 80.0 and p["difficulty"] == 3.0     # page-weighted
    assert p["rating_distribution"] == {"1": 0, "2": 0, "3": 1, "4": 0, "5": 1}
    assert p["grade_distribution"] == {"A": 2}


def test_course_and_professor_course_rows():
    rows, _ = build_summaries(PAGES, [review(1, code="CS3500"), review(2, code="CS2500", q=1)],
                              PAGE_SLUG, {}, ["olin-guha"])
    by = rows_by(rows)
    assert by[("", "CS3500")]["num_ratings"] == 1
    assert by[("olin-guha", "CS2500")]["rating"] == 1.0
    assert by[("", "CS2500")]["would_take_again_pct"] is None


def test_review_without_a_page_falls_back_to_name_key():
    r = review(1, name="O. Guha", dept="Other")
    rows, coverage = build_summaries(PAGES, [r], PAGE_SLUG, {"olin guha": "olin-guha"}, ["olin-guha"])
    assert rows_by(rows)[("olin-guha", "")]["num_ratings"] == 1
    assert coverage == {"reviews": 1, "via_page": 0, "via_name_key": 1, "unmapped": 0, "name_key_alone": 1}


def test_unmapped_reviews_are_counted_not_summarized():
    rows, coverage = build_summaries(PAGES, [review(1, name="Nobody", key="nobody")], PAGE_SLUG, {}, ["olin-guha"])
    assert coverage["unmapped"] == 1
    assert ("", "CS3500") not in rows_by(rows)


def test_linked_professor_without_reviews_gets_a_row():
    rows, _ = build_summaries(PAGES, [], PAGE_SLUG, {}, ["olin-guha"])
    p = rows_by(rows)[("olin-guha", "")]
    assert p["num_ratings"] == 0
    assert p["rating"] == 4.0          # falls back to the page's own rating
    assert p["rating_distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}


def test_pages_are_rating_count_weighted():
    pages = PAGES + [{**PAGES[0], "name": "Olin Guha", "department": "Khoury", "rating": 2.0,
                      "num_ratings": 30, "would_take_again_pct": "40%", "level_of_difficulty": 5.0}]
    rows, _ = build_summaries(pages, [], {**PAGE_SLUG, ("Olin Guha", "Khoury"): "olin-guha"}, {}, ["olin-guha"])
    p = rows_by(rows)[("olin-guha", "")]
    assert p["would_take_again_pct"] == 50.0      # (80*10 + 40*30) / 40
    assert p["difficulty"] == 4.5                 # (3*10 + 5*30) / 40
    assert p["rating"] == 2.5                     # no stored reviews: (4*10 + 2*30) / 40
