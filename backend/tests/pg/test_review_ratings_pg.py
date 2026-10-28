"""review_ratings' merge against the real one-per-device unique index."""

import uuid

import psycopg2.extras
import pytest

import review_ratings
from tests.pg.pgutil import rows, truncate


@pytest.fixture(autouse=True)
def clean(pg):
    truncate(pg, "survey_ratings", "survey_pending_professors", "professors", "banner_course_instructors",
             "rating_flags")


def insert(pg, slug, pending, updated_at, rating):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO survey_ratings (id, professor_slug, pending_professor_id, "
            "course_code, rating, hours, status, device_hash, new_device, network_type, "
            "updated_at) VALUES (%s, %s, %s, 'CS2500', %s, '3-4', 'accepted', 'd1', "
            "true, 'unknown', %s)",
            (str(uuid.uuid4()), slug, pending, rating, updated_at))


def test_merge_professor_against_the_real_index(pg):
    pending = str(uuid.uuid4())
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors (slug, name, name_key) "
                    "VALUES ('jane-doe', 'Jane Doe', 'jane doe')")
        cur.execute("INSERT INTO survey_pending_professors (id, name, name_key) "
                    "VALUES (%s, 'J Doe', 'j doe')", (pending,))
    insert(pg, "jane-doe", None, "2026-10-01T00:00:00Z", 2)
    insert(pg, None, pending, "2026-10-10T00:00:00Z", 5)
    pg.commit()

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_ratings.merge_professor(cur, pending, "jane-doe")
    pg.commit()

    left = rows(pg, "SELECT professor_slug, pending_professor_id, rating "
                    "FROM survey_ratings WHERE device_hash = 'd1' AND course_code = 'CS2500'")
    assert left == [{"professor_slug": "jane-doe", "pending_professor_id": None, "rating": 5}]


def test_merge_professor_keeps_the_existing_rating_when_it_is_newer(pg):
    pending = str(uuid.uuid4())
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors (slug, name, name_key) "
                    "VALUES ('jane-doe', 'Jane Doe', 'jane doe')")
        cur.execute("INSERT INTO survey_pending_professors (id, name, name_key) "
                    "VALUES (%s, 'J Doe', 'j doe')", (pending,))
    insert(pg, "jane-doe", None, "2026-10-10T00:00:00Z", 4)
    insert(pg, None, pending, "2026-10-01T00:00:00Z", 1)
    pg.commit()

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_ratings.merge_professor(cur, pending, "jane-doe")
    pg.commit()

    left = rows(pg, "SELECT professor_slug, pending_professor_id, rating "
                    "FROM survey_ratings WHERE device_hash = 'd1' AND course_code = 'CS2500'")
    assert left == [{"professor_slug": "jane-doe", "pending_professor_id": None, "rating": 4}]


@pytest.mark.parametrize("before, after", [(None, "comment_removed"),
                                           ("too_fast", "too_fast,comment_removed"),
                                           ("comment_removed", "comment_removed")])
def test_remove_comment_marks_the_row_and_keeps_its_hash(pg, monkeypatch, before, after):
    import survey_reviews
    secret = "s" * 32
    monkeypatch.setenv("RATING_SECRET", secret)
    rating_id = str(uuid.uuid4())
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO survey_ratings (id, professor_slug, course_code, rating, hours, comment, comment_hash, "
            "status, hold_reasons, device_hash, new_device, network_type) "
            "VALUES (%s, 'jane-doe', 'CS2500', 4, '3-4', 'rude', 'h1', 'accepted', %s, 'd1', true, 'unknown')",
            (rating_id, before))
    pg.commit()

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_ratings.remove_comment(cur, survey_reviews.public_id(secret, rating_id))
    pg.commit()

    assert rows(pg, "SELECT comment, comment_hash, status, hold_reasons FROM survey_ratings") == [
        {"comment": None, "comment_hash": "h1", "status": "accepted", "hold_reasons": after}]


def test_merge_holds_moved_ratings_on_a_pair_banner_never_saw(pg):
    # Merging a name variant is a judgment about the person, not about who taught the course.
    pending = str(uuid.uuid4())
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors (slug, name, name_key) "
                    "VALUES ('jane-doe', 'Jane Doe', 'jane doe')")
        cur.execute("INSERT INTO survey_pending_professors (id, name, name_key) "
                    "VALUES (%s, 'J Doe', 'j doe')", (pending,))
        cur.execute(
            "INSERT INTO banner_course_instructors (subject_course, instructor_key, professor_slug, "
            "match_method, terms_taught, sections, first_term_code, last_term_code, last_term_label) "
            "VALUES ('CS2500', 'k1', 'jane-doe', 'exact', 1, 1, '202510', '202510', 'Fall 2024')")
    insert(pg, None, pending, "2026-10-10T00:00:00Z", 5)
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO survey_ratings (id, pending_professor_id, course_code, rating, hours, status, "
            "hold_reasons, device_hash, new_device, network_type) "
            "VALUES (%s, %s, 'CS3500', 1, '3-4', 'held', 'too_fast', 'd2', true, 'unknown')",
            (str(uuid.uuid4()), pending))
    pg.commit()

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        summary = review_ratings.merge_professor(cur, pending, "jane-doe")
    pg.commit()

    assert "moved 2 rating(s), held 1" in summary
    left = rows(pg, "SELECT course_code, status, hold_reasons FROM survey_ratings ORDER BY course_code")
    assert left == [{"course_code": "CS2500", "status": "accepted", "hold_reasons": None},
                    {"course_code": "CS3500", "status": "held", "hold_reasons": "too_fast,unverified_pair"}]


def insert_held(pg, rating_id, reasons="burst_ip", device="dev1"):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO survey_ratings (id, professor_slug, course_code, rating, hours, status, "
            "hold_reasons, device_hash, ip_hash, new_device, network_type) "
            "VALUES (%s, 'jane-doe', 'CS2500', 1, '3-4', 'held', %s, %s, 'ip1', true, 'other')",
            (rating_id, reasons, device))
    pg.commit()


def test_abuse_reject_flags_then_deletes(pg):
    rating_id = str(uuid.uuid4())
    insert_held(pg, rating_id)
    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_ratings.reject_rating(cur, rating_id[:8], abuse=True)
    pg.commit()
    assert rows(pg, "SELECT kind, value_hash FROM rating_flags ORDER BY kind") == [
        {"kind": "device", "value_hash": "dev1"}, {"kind": "ip", "value_hash": "ip1"}]
    assert rows(pg, "SELECT id FROM survey_ratings") == []


def test_abuse_reject_of_a_missing_id_leaves_no_flag(pg):
    args = review_ratings.parse_args(["reject-rating", "--abuse", "deadbeef"])
    with pytest.raises(review_ratings.ReviewError):
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            review_ratings.run(cur, args)
    pg.rollback()
    assert rows(pg, "SELECT 1 FROM rating_flags") == []


def test_abuse_reject_rolls_back_flags_when_a_later_id_fails(pg):
    rating_id = str(uuid.uuid4())
    insert_held(pg, rating_id)
    args = review_ratings.parse_args(["reject-rating", "--abuse", rating_id[:8], "deadbeef"])
    with pytest.raises(review_ratings.ReviewError):
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            review_ratings.run(cur, args)
    pg.rollback()
    assert rows(pg, "SELECT 1 FROM rating_flags") == []
    assert [str(r["id"]) for r in rows(pg, "SELECT id FROM survey_ratings")] == [rating_id]


def test_reject_still_deletes_rows_held_by_the_new_reasons(pg):
    near, skew = str(uuid.uuid4()), str(uuid.uuid4())
    insert_held(pg, near, "near_duplicate")
    insert_held(pg, skew, "skew_week", device="dev2")
    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_ratings.reject_rating(cur, near, skew)
    pg.commit()
    assert rows(pg, "SELECT id FROM survey_ratings") == []
