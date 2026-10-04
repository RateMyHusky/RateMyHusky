"""sources.rmp: only what Rate My Professors measured."""

import rmp

ROW = {"rating": 4.25, "difficulty": 3.0, "would_take_again_pct": 80.0, "num_ratings": 12,
       "rating_distribution": {"5": 12}, "grade_distribution": {"A": 3}}
URL = "https://www.ratemyprofessors.com/professor/9"


def _review(quality=5, grade="A"):
    return {"course": "CS3500", "course_code": "CS3500", "quality": quality, "difficulty": 3, "date": "2024",
            "tags": "", "attendance": "", "grade": grade, "textbook": "",
            "online_class": "", "comment": "ok"}


def test_section_keys_are_fixed():
    assert set(rmp.build_section(ROW, URL, [])) == {
        "available", "rating", "difficulty", "wouldTakeAgainPct", "numRatings",
        "professorUrl", "ratingDistribution", "gradeDistribution", "reviews"}


def test_section_reads_the_rmp_summary_row():
    s = rmp.build_section(ROW, URL, [])
    assert (s["available"], s["rating"], s["difficulty"], s["wouldTakeAgainPct"], s["numRatings"]) == \
        (True, 4.25, 3.0, 80.0, 12)
    assert s["professorUrl"] == URL
    assert s["ratingDistribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 12}
    assert s["gradeDistribution"] == {"A": 3}


def test_no_row_is_unavailable_with_null_numbers():
    s = rmp.build_section(None, None, [])
    assert s["available"] is False
    assert (s["rating"], s["difficulty"], s["wouldTakeAgainPct"]) == (None, None, None)
    assert s["numRatings"] == 0
    assert s["ratingDistribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}


def test_distribution_always_has_every_star():
    assert rmp.distribution({"5": 2}) == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 2}
    assert rmp.distribution(None) == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}


def test_stat_treats_zero_and_none_as_missing():
    assert rmp.stat(0, 2) is None
    assert rmp.stat(None, 2) is None
    assert rmp.stat(3.456, 2) == 3.46


def test_pct_keeps_zero_and_nulls_none():
    assert rmp.pct(0) == 0.0
    assert rmp.pct(None) is None
    assert rmp.pct(87.66) == 87.7


def test_rating_distribution_counts_each_star():
    d = rmp.rating_distribution([_review(5), _review(5), _review(1), _review(0)])
    assert d == {"1": 1, "2": 0, "3": 0, "4": 0, "5": 2}


def test_grade_distribution_skips_non_grades():
    d = rmp.grade_distribution([_review(grade="A"), _review(grade="N/A"),
                                _review(grade="Not sure yet"), _review(grade="")])
    assert d == {"A": 1}


def test_fetch_reviews_reads_rmp_reviews_with_the_moderation_filter(monkeypatch):
    seen = []
    monkeypatch.setattr(rmp.moderation, "sql_filter", lambda alias="": " AND ok")
    rows = rmp.fetch_reviews("olin guha", lambda sql, p: seen.append(sql) or [
        {**_review(), "comment": "a &amp; b"}], lambda t: t.replace("&amp;", "&"))
    assert "FROM rmp_reviews" in seen[0] and seen[0].rstrip().endswith("AND ok")
    assert rows[0]["comment"] == "a & b"
    assert "courseCode" in rows[0]
