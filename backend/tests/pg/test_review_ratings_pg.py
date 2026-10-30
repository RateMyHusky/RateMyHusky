"""review_ratings' merge against the real one-per-device unique index."""

import uuid

import psycopg2.errors
import psycopg2.extras
import pytest

import review_ratings
from tests.pg.pgutil import rows, truncate


@pytest.fixture(autouse=True)
def clean(pg):
    truncate(pg, "survey_ratings", "survey_pending_professors", "professors", "banner_course_instructors",
             "rating_flags", "professor_aliases")


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


@pytest.mark.parametrize("before", [None, "too_fast"])
def test_remove_comment_clears_only_the_comment_and_keeps_its_hash(pg, monkeypatch, before):
    import survey_reviews
    secret = "s" * 32
    monkeypatch.setenv("RATING_SECRET", secret)
    rating_id = str(uuid.uuid4())
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO survey_ratings (id, professor_slug, course_code, rating, hours, comment, comment_hash, "
            "status, hold_reasons, device_hash, new_device, network_type, comment_status) "
            "VALUES (%s, 'jane-doe', 'CS2500', 4, '3-4', 'rude', 'h1', 'accepted', %s, 'd1', true, 'unknown', "
            "'approved')",
            (rating_id, before))
    pg.commit()

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_ratings.remove_comment(cur, survey_reviews.public_id(secret, rating_id))
    pg.commit()

    assert rows(pg, "SELECT comment, comment_hash, comment_status, status, hold_reasons FROM survey_ratings") == [
        {"comment": None, "comment_hash": "h1", "comment_status": None, "status": "accepted", "hold_reasons": before}]


def test_approve_and_reject_comment_leave_the_rating_counting(pg):
    ids = [str(uuid.uuid4()) for _ in range(3)]
    with pg.cursor() as cur:
        for i, (rating_id, comment_status) in enumerate(zip(ids, ("pending", "pending", "approved"))):
            cur.execute(
                "INSERT INTO survey_ratings (id, professor_slug, course_code, rating, hours, comment, comment_hash, "
                "status, device_hash, new_device, network_type, comment_status) "
                "VALUES (%s, 'jane-doe', 'CS2500', 4, '3-4', 'text', 'h1', 'accepted', %s, true, 'unknown', %s)",
                (rating_id, f"d{i}", comment_status))
    pg.commit()
    listed = {r["id"]: review_ratings.comment_version(r["id"], r["updated_at"])
              for r in rows(pg, "SELECT id::text AS id, updated_at FROM survey_ratings")}
    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_ratings.approve_comment(cur, listed[ids[0]])
        review_ratings.reject_comment(cur, ids[1][:8])
        with pytest.raises(review_ratings.ReviewError):   # already approved: not waiting
            review_ratings.approve_comment(cur, listed[ids[2]])
    pg.commit()
    got = {r["id"]: r for r in rows(pg, "SELECT id::text AS id, comment, comment_status, status, hold_reasons "
                                        "FROM survey_ratings")}
    assert got[ids[0]] == {"id": ids[0], "comment": "text", "comment_status": "approved",
                           "status": "accepted", "hold_reasons": None}
    assert got[ids[1]] == {"id": ids[1], "comment": None, "comment_status": None,
                           "status": "accepted", "hold_reasons": None}


def test_an_edit_between_list_and_approve_comment_is_not_approved(pg):
    # The reviewer read "Hard but fair"; the student edits it before the approval runs.
    import ratings
    rating_id = str(uuid.uuid4())
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO survey_ratings (id, professor_slug, course_code, rating, hours, comment, status, "
            "device_hash, new_device, network_type, comment_status) "
            "VALUES (%s, 'jane-doe', 'CS2500', 4, '3-4', 'Hard but fair', 'accepted', 'd1', true, 'unknown', "
            "'pending')", (rating_id,))
    pg.commit()
    (listed,) = rows(pg, "SELECT updated_at FROM survey_ratings")
    version = review_ratings.comment_version(rating_id, listed["updated_at"])

    def write(sql, params):
        with pg.cursor() as cur:
            cur.execute(sql, params)
        pg.commit()
    row = {c: None for c in ratings.RATING_COLUMNS if c != "id"}
    row.update(professor_slug="jane-doe", course_code="CS2500", rating=4, hours="3-4", status="accepted",
               device_hash="d1", new_device=True, network_type="unknown", collection="turnstile+device",
               comment="something abusive the reviewer never read")
    ratings.save_rating(row, {"id": rating_id, "hold_reasons": None}, write)

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        with pytest.raises(review_ratings.ReviewError):
            review_ratings.approve_comment(cur, version)
    pg.rollback()
    assert rows(pg, "SELECT comment_status FROM survey_ratings") == [{"comment_status": "pending"}]


def test_an_edit_after_reject_comment_keeps_counting_and_stays_in_the_surge_scan(pg):
    import ratings
    rating_id = str(uuid.uuid4())
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO survey_ratings (id, professor_slug, course_code, rating, hours, comment, status, "
            "device_hash, new_device, network_type, comment_status) "
            "VALUES (%s, 'jane-doe', 'CS2500', 4, '3-4', 'junk', 'accepted', 'd1', true, 'unknown', 'pending')",
            (rating_id,))
    pg.commit()
    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_ratings.reject_comment(cur, rating_id[:8])
    pg.commit()
    (row,) = rows(pg, "SELECT status, hold_reasons FROM survey_ratings")
    # hold_reasons NULL: pipeline/survey.surge_ids still counts this rating's edits.
    assert row == {"status": "accepted", "hold_reasons": None}


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


def test_alias_unique_per_key_and_slug_and_approve_reject_against_the_real_table(pg):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professor_aliases (alias_key, slug, source) VALUES ('bob', 'robert-smith', 'merge')")
    pg.commit()
    with pytest.raises(psycopg2.errors.UniqueViolation):
        with pg.cursor() as cur:
            cur.execute("INSERT INTO professor_aliases (alias_key, slug, source) "
                        "VALUES ('bob', 'robert-smith', 'comment')")
    pg.rollback()
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professor_aliases (alias_key, slug, source) "
                    "VALUES ('bob', 'robert-smith', 'comment') ON CONFLICT (alias_key, slug) DO NOTHING")
    pg.commit()
    alias_id = rows(pg, "SELECT id FROM professor_aliases")[0]["id"]
    assert rows(pg, "SELECT status FROM professor_aliases") == [{"status": "pending"}]

    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        review_ratings.approve_alias(cur, str(alias_id))
        with pytest.raises(review_ratings.ReviewError):
            review_ratings.approve_alias(cur, str(alias_id))
        review_ratings.reject_alias(cur, str(alias_id))
    pg.commit()
    assert rows(pg, "SELECT status FROM professor_aliases") == [{"status": "rejected"}]
