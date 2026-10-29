"""Student reviews for the professor page: which rows show and what they carry."""

import uuid
from datetime import datetime, timezone

from survey_reviews import comment_count, public_id, shape_reviews, when

CREATED = datetime(2025, 12, 1, tzinfo=timezone.utc)
UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def row(**kw):
    base = {"id": uuid.uuid4(), "course_code": "PHIL2325", "term_label": "Fall 2025", "term_enrollment": 40, "terms_in_year": 2,
            "rating": 4, "comment": "Good.", "created_at": CREATED,
            "updated_at": datetime(2026, 10, 20, tzinfo=timezone.utc)}
    return {**base, **kw}


def rid(u):
    return "abc"


def test_when_shows_the_term_at_the_threshold():
    assert when("Fall 2025", 15, 1, CREATED) == "Fall 2025"


def test_when_falls_back_to_the_year_below_the_threshold():
    assert when("Summer 1 2025", 14, 2, CREATED) == "2025"


def test_when_falls_back_to_the_year_without_banner_enrollment():
    assert when("Spring 2024", None, 3, CREATED) == "2024"


def test_when_shows_no_date_when_the_year_has_only_that_term():
    # The teaching history would turn "2025" back into the one small section.
    assert when("Fall 2025", 14, 1, CREATED) == ""
    assert when("Fall 2025", None, 0, CREATED) == ""
    assert when("Fall 2025", None, None, CREATED) == ""


def test_when_without_a_term_is_the_created_year():
    assert when(None, None, None, datetime(2026, 10, 20, tzinfo=timezone.utc)) == "2026"


def test_blank_comments_are_not_reviews():
    rows = [row(comment="ok"), row(comment=None), row(comment="  ")]
    assert [r["comment"] for r in shape_reviews(rows, rid, str)] == ["ok"]
    assert comment_count(rows) == 1


def test_review_keys_are_exact_and_grade_free():
    (r,) = shape_reviews([row(grade="A")], rid, str)
    # No exact date: it would pin the term that `when` hides in a small class.
    assert r == {"id": "abc", "course": "PHIL2325", "when": "Fall 2025", "rating": 4, "comment": "Good."}


def test_id_comes_from_review_id_not_the_uuid():
    (r,) = shape_reviews([row(id=UUID)], lambda u: "h" + str(u)[:3], str)
    assert r["id"] == "h" + str(UUID)[:3]


def test_no_review_id_means_no_reviews():
    assert shape_reviews([row()], None, str) == []


def test_comment_is_sanitized():
    (r,) = shape_reviews([row(comment="<b>hi</b>")], rid, lambda t: t.replace("<b>", "").replace("</b>", ""))
    assert r["comment"] == "hi"


def test_reviews_capped_at_200():
    assert len(shape_reviews([row() for _ in range(201)], rid, str)) == 200
    assert comment_count([row() for _ in range(201)]) == 201


def test_public_id_is_a_keyed_12_char_hash():
    a = public_id("s" * 32, UUID)
    assert len(a) == 12 and a == public_id("s" * 32, str(UUID)) and a != public_id("t" * 32, UUID)
