"""The survey rating tables' unique index and CHECKs against real PostgreSQL."""

import uuid

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from tests.pg.pgutil import rows, scalar, truncate


@pytest.fixture(autouse=True)
def clean(pg):
    truncate(pg, "survey_ratings")


def insert(pg, device, slug, pending_prof, course, pending_course,
           rating=4, status="accepted"):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO survey_ratings (id, professor_slug, pending_professor_id, "
            "course_code, pending_course_id, rating, hours, status, device_hash, "
            "new_device, network_type) "
            "VALUES (%s, %s, %s, %s, %s, %s, '3-4', %s, %s, true, 'unknown')",
            (str(uuid.uuid4()), slug, pending_prof, course, pending_course,
             rating, status, device))


def test_one_rating_per_device_and_key(pg):
    insert(pg, "d1", "jane-doe", None, "CS2500", None)
    pg.commit()
    with pytest.raises(psycopg2.errors.UniqueViolation):
        insert(pg, "d1", "jane-doe", None, "CS2500", None)
    pg.rollback()
    insert(pg, "d1", "jane-doe", None, "CS3500", None)
    pg.commit()
    assert scalar(pg, "SELECT count(*) FROM survey_ratings") == 2


@pytest.mark.parametrize("kwargs", [
    {"rating": 6},
    {"status": "published"},
    {"slug": None},
])
def test_survey_checks_reject_bad_rows(pg, kwargs):
    row = {"slug": "jane-doe", "rating": 4, "status": "accepted"}
    row.update(kwargs)
    with pytest.raises(psycopg2.errors.CheckViolation):
        insert(pg, "d1", row["slug"], None, "CS2500", None,
               rating=row["rating"], status=row["status"])
    pg.rollback()


def test_upsert_keeps_a_held_row_held(pg):
    import ratings

    insert(pg, "d1", "jane-doe", None, "CS2500", None, rating=2, status="held")
    pg.commit()
    row = {c: None for c in ratings.RATING_COLUMNS if c != "id"}
    row.update(professor_slug="jane-doe", course_code="CS2500", rating=5, hours="3-4",
               status="accepted", device_hash="d1", new_device=False,
               network_type="unknown", collection="turnstile+device")

    def write(sql, params):
        with pg.cursor() as cur:
            cur.execute(sql, params)
        pg.commit()

    ratings.save_rating(row, None, write)
    assert scalar(pg, "SELECT count(*) FROM survey_ratings") == 1
    assert scalar(pg, "SELECT status FROM survey_ratings") == "held"
    assert scalar(pg, "SELECT rating FROM survey_ratings") == 5


def pg_write(pg):
    """Like server._write: commits and returns the RETURNING rows as dicts."""
    def write(sql, params):
        with pg.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            found = cur.fetchall() if cur.description else None
        pg.commit()
        return found
    return write


def pg_query_one(pg):
    def query_one(sql, params):
        found = rows(pg, sql, params)
        return found[0] if found else None
    return query_one


def test_pending_rows_are_one_per_key_against_the_real_index(pg):
    import ratings

    truncate(pg, "survey_pending_professors", "survey_pending_courses")
    write, query_one = pg_write(pg), pg_query_one(pg)
    first = ratings.pending_professor("Jane Doe", None, query_one, write)
    assert first[1] is True
    assert ratings.pending_professor("jane  DOE", None, query_one, write) == (first[0], False)
    first = ratings.pending_course("ZZ9999", "New", query_one, write)
    assert ratings.pending_course("ZZ9999", "Other", query_one, write) == (first[0], False)
    assert scalar(pg, "SELECT count(*) FROM survey_pending_professors") == 1
    assert scalar(pg, "SELECT count(*) FROM survey_pending_courses") == 1
    # A resolved row no longer blocks a new pending one for the same code.
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_pending_courses SET status = 'approved'")
    pg.commit()
    assert ratings.pending_course("ZZ9999", "New", query_one, write)[1] is True


def test_upsert_keeps_new_device_and_merges_hold_reasons(pg):
    import ratings

    insert(pg, "d1", "jane-doe", None, "CS2500", None, status="held")
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'burst_ip,duplicate_comment'")
    pg.commit()
    row = {c: None for c in ratings.RATING_COLUMNS if c != "id"}
    row.update(professor_slug="jane-doe", course_code="CS2500", rating=5, hours="3-4",
               status="held", hold_reasons="too_fast", device_hash="d1", new_device=False,
               network_type="unknown", collection="turnstile+device")
    key = ratings.rating_key(row, None, None)
    existing = ratings.existing_rating("d1", key, pg_query_one(pg))
    ratings.save_rating(row, existing, pg_write(pg))
    (saved,) = rows(pg, "SELECT new_device, hold_reasons FROM survey_ratings")
    assert saved == {"new_device": True, "hold_reasons": "burst_ip,duplicate_comment,too_fast"}


def test_an_edit_without_a_difficulty_keeps_the_stored_one(pg):
    import ratings

    insert(pg, "d1", "jane-doe", None, "CS2500", None)
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET difficulty = 4")
    pg.commit()
    row = {c: None for c in ratings.RATING_COLUMNS if c != "id"}
    row.update(professor_slug="jane-doe", course_code="CS2500", rating=5, hours="3-4",
               status="accepted", device_hash="d1", new_device=False,
               network_type="unknown", collection="turnstile+device")
    key = ratings.rating_key(row, None, None)
    ratings.save_rating(row, ratings.existing_rating("d1", key, pg_query_one(pg)), pg_write(pg))
    assert rows(pg, "SELECT rating, difficulty FROM survey_ratings") == [{"rating": 5, "difficulty": 4}]
    ratings.save_rating({**row, "difficulty": 2}, ratings.existing_rating("d1", key, pg_query_one(pg)),
                        pg_write(pg))
    assert rows(pg, "SELECT difficulty FROM survey_ratings") == [{"difficulty": 2}]


def test_hold_burst_skips_returning_devices_and_approved_rows(pg):
    import ratings
    from datetime import datetime, timezone

    insert(pg, "d1", "jane-doe", None, "CS2500", None)  # new device
    insert(pg, "d2", "jane-doe", None, "CS2500", None)  # returning device
    insert(pg, "d3", "jane-doe", None, "CS2500", None)  # approved by a reviewer
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET new_device = false WHERE device_hash = 'd2'")
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'burst_pair' WHERE device_hash = 'd3'")
    pg.commit()
    key = {"professor_slug": "jane-doe", "pending_professor_id": None,
           "course_code": "CS2500", "pending_course_id": None}
    assert ratings.hold_burst(["burst_pair"], key, None, None, pg_write(pg),
                              datetime.now(timezone.utc)) == {"jane-doe"}
    held = rows(pg, "SELECT device_hash FROM survey_ratings WHERE status = 'held'")
    assert [r["device_hash"] for r in held] == ["d1"]


def test_burst_queries_run_and_a_held_burst_pauses_its_scope(pg):
    import ratings
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    key = {"professor_slug": "jane-doe", "pending_professor_id": None,
           "course_code": "CS2500", "pending_course_id": None}
    query_one = pg_query_one(pg)
    assert ratings.burst_reasons(key, "ip", "pre", "other", query_one, now) == []
    # A pair burst on another course pauses only that pair.
    insert(pg, "d1", "jane-doe", None, "CS3500", None, status="held")
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'no_timer,burst_pair'")
    pg.commit()
    assert ratings.burst_reasons(key, "ip", "pre", "other", query_one, now) == []
    # A professor burst pauses every course of theirs, until a reviewer clears it.
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'no_timer,burst_prof'")
    pg.commit()
    assert ratings.burst_reasons(key, "ip", "pre", "other", query_one, now) == ["burst_pause"]
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET status = 'accepted'")
    pg.commit()
    assert ratings.burst_reasons(key, "ip", "pre", "other", query_one, now) == []


def test_pair_taught_reads_the_real_banner_table(pg):
    import ratings

    truncate(pg, "banner_course_instructors")
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO banner_course_instructors (subject_course, instructor_key, professor_slug, "
            "match_method, terms_taught, sections, first_term_code, last_term_code, last_term_label) "
            "VALUES ('CS2500', 'k1', 'jane-doe', 'exact', 1, 1, '202510', '202510', 'Fall 2024')")
    pg.commit()
    assert ratings.pair_taught("jane-doe", "CS2500", pg_query_one(pg))
    assert not ratings.pair_taught("jane-doe", "CS3500", pg_query_one(pg))


def test_an_approved_unverified_pair_rating_makes_the_pair_taught(pg):
    # A professor or course approved from the form is in neither Banner nor RMP.
    import ratings

    truncate(pg, "banner_course_instructors", "source_summary")
    insert(pg, "d1", "new-prof", None, "CS3500", None, status="held")
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'too_fast,unverified_pair'")
    pg.commit()
    assert not ratings.pair_taught("new-prof", "CS3500", pg_query_one(pg))
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET status = 'accepted'")  # review_ratings approve-rating
    pg.commit()
    assert ratings.pair_taught("new-prof", "CS3500", pg_query_one(pg))
    assert not ratings.pair_taught("new-prof", "CS2500", pg_query_one(pg))


def test_a_clean_edit_of_an_approved_rating_keeps_its_hold_reasons(pg):
    import ratings

    insert(pg, "d1", "jane-doe", None, "CS2500", None)
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'weekly_surge'")  # approved by a reviewer
    pg.commit()
    row = {c: None for c in ratings.RATING_COLUMNS if c != "id"}
    row.update(professor_slug="jane-doe", course_code="CS2500", rating=1, hours="3-4",
               status="accepted", device_hash="d1", new_device=False,
               network_type="unknown", collection="turnstile+device")
    existing = ratings.existing_rating("d1", ratings.rating_key(row, None, None), pg_query_one(pg))
    ratings.save_rating(row, existing, pg_write(pg))
    (saved,) = rows(pg, "SELECT status, rating, hold_reasons FROM survey_ratings")
    assert saved == {"status": "accepted", "rating": 1, "hold_reasons": "weekly_surge"}


def test_a_wave_of_edits_to_old_ratings_trips_the_bursts(pg):
    # An edit keeps created_at and bumps updated_at, which every burst window reads.
    import ratings
    from datetime import datetime, timezone

    for i in range(ratings.PROF_BURST):
        insert(pg, f"d{i}", "jane-doe", None, "CS2500", None)
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET created_at = now() - interval '40 days'")
    pg.commit()
    key = {"professor_slug": "jane-doe", "pending_professor_id": None,
           "course_code": "CS2500", "pending_course_id": None}
    assert ratings.burst_reasons(key, "ip", "pre", "other", pg_query_one(pg),
                                 datetime.now(timezone.utc)) == ["burst_pair", "burst_prof"]


def test_apply_surge_holds_holds_only_unreviewed_accepted_rows(pg):
    from pipeline import survey

    insert(pg, "d1", "jane-doe", None, "CS2500", None)
    insert(pg, "d2", "jane-doe", None, "CS3500", None)
    insert(pg, "d3", "jane-doe", None, "CS4500", None)
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'burst_prof' WHERE device_hash = 'd2'")  # approved
    pg.commit()
    ids = [r["id"] for r in rows(pg, "SELECT id::text AS id FROM survey_ratings ORDER BY device_hash")]
    assert survey.apply_surge_holds(pg, set(ids)) == 2
    held = rows(pg, "SELECT device_hash, hold_reasons FROM survey_ratings WHERE status = 'held' ORDER BY device_hash")
    assert held == [{"device_hash": "d1", "hold_reasons": "weekly_surge"},
                    {"device_hash": "d3", "hold_reasons": "weekly_surge"}]
    assert survey.apply_surge_holds(pg, set()) == 0


def test_a_comment_waits_for_review_until_its_text_is_approved(pg):
    import ratings

    row = {c: None for c in ratings.RATING_COLUMNS if c != "id"}
    row.update(professor_slug="jane-doe", course_code="CS2500", rating=5, hours="3-4",
               status="accepted", device_hash="d1", new_device=True,
               network_type="unknown", collection="turnstile+device")

    def save(comment):
        existing = ratings.existing_rating("d1", ratings.rating_key(row, None, None), lambda q, p: (
            rows(pg, q, p) or [None])[0])
        ratings.save_rating({**row, "comment": comment}, existing, pg_write(pg))
        return scalar(pg, "SELECT comment_status FROM survey_ratings")

    assert save("Hard but fair") == "pending"
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET comment_status = 'approved'")
    pg.commit()
    assert save("Hard but fair") == "approved"   # an edit to the numbers keeps the approved text
    assert save("Hard but fair, and rude") == "pending"
    assert save(None) is None
    assert save("Back again") == "pending"
    assert scalar(pg, "SELECT count(*) FROM survey_ratings") == 1


def test_comment_status_check_rejects_other_values(pg):
    insert(pg, "d1", "jane-doe", None, "CS2500", None)
    pg.commit()
    with pytest.raises(psycopg2.errors.CheckViolation):
        with pg.cursor() as cur:
            cur.execute("UPDATE survey_ratings SET comment_status = 'shown'")
    pg.rollback()


def test_hold_matches_holds_accepted_appends_held_and_skips_approved(pg):
    import ratings

    insert(pg, "d1", "jane-doe", None, "CS2500", None)  # accepted, no reasons
    insert(pg, "d2", "jane-doe", None, "CS2500", None, status="held")
    insert(pg, "d3", "jane-doe", None, "CS2500", None)  # approved by a reviewer
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'no_timer' WHERE device_hash = 'd2'")
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'burst_prof' WHERE device_hash = 'd3'")
    pg.commit()
    ids = [r["id"] for r in rows(pg, "SELECT id FROM survey_ratings")]
    write = pg_write(pg)

    def state():
        return {r["device_hash"]: (r["status"], r["hold_reasons"])
                for r in rows(pg, "SELECT device_hash, status, hold_reasons FROM survey_ratings")}

    expected = {"d1": ("held", "near_duplicate"), "d2": ("held", "no_timer,near_duplicate"),
                "d3": ("accepted", "burst_prof")}
    for _ in range(2):
        for device in ("d1", "d2", "d3"):
            ratings.hold_matches(ids, "near_duplicate", device, None, None, "residential", write)
        assert state() == expected


def test_skew_week_aggregate_and_hold_back(pg):
    import ratings
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    truncate(pg, "professors_catalog")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors_catalog (slug, name, name_key, avg_rating) "
                    "VALUES ('jane-doe', 'Jane Doe', 'jane doe', 4.2)")
    for i in range(7):
        insert(pg, f"d{i}", "jane-doe", None, "CS2500", None, rating=1 + i % 2)
    insert(pg, "old", "jane-doe", None, "CS2500", None, rating=1)
    insert(pg, "approved", "jane-doe", None, "CS2500", None, rating=1)
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET created_at = now() - interval '9 days' "
                    "WHERE device_hash = 'old'")
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'burst_prof' "
                    "WHERE device_hash = 'approved'")
    pg.commit()
    key = {"professor_slug": "jane-doe", "pending_professor_id": None,
           "course_code": "CS2500", "pending_course_id": None}
    assert ratings.skew_week(key, 1, True, None, pg_query_one(pg), now) is True
    ratings.hold_skew_week(key, pg_write(pg), now)
    held = [r["device_hash"] for r in rows(
        pg, "SELECT device_hash FROM survey_ratings WHERE hold_reasons = 'skew_week'")]
    assert sorted(held) == [f"d{i}" for i in range(7)]


def test_hold_skew_week_adds_its_reason_to_rows_already_held(pg):
    import ratings
    from datetime import datetime, timezone

    reviewed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for device in ("fast", "both", "other", "escalated", "rejected", "pair", "burst_pair"):
        insert(pg, device, "jane-doe" if device != "other" else "sam-lee", None, "CS2500", None, status="held")
    with pg.cursor() as cur:
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'too_fast' "
                    "WHERE device_hash IN ('fast', 'other', 'escalated', 'rejected')")
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'no_timer,skew_week' WHERE device_hash = 'both'")
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'too_fast,unverified_pair' WHERE device_hash = 'pair'")
        cur.execute("UPDATE survey_ratings SET hold_reasons = 'burst_pair' WHERE device_hash = 'burst_pair'")
        cur.execute("UPDATE survey_ratings SET agent_decision = %s, agent_reason = 'x', agent_reviewed_at = %s "
                    "WHERE device_hash = %s", ("escalate", reviewed, "escalated"))
        cur.execute("UPDATE survey_ratings SET agent_decision = %s, agent_reason = 'x', agent_reviewed_at = %s "
                    "WHERE device_hash = %s", ("reject", reviewed, "rejected"))
    pg.commit()
    before = {r["device_hash"]: r["updated_at"] for r in rows(pg, "SELECT device_hash, updated_at FROM survey_ratings")}
    key = {"professor_slug": "jane-doe", "pending_professor_id": None,
           "course_code": "CS2500", "pending_course_id": None}
    # Only rows the agent could approve on their own join; an escalate-only reason or a reject stays out.
    expected = {"fast": "too_fast,skew_week", "both": "no_timer,skew_week", "other": "too_fast",
                "escalated": "too_fast,skew_week", "rejected": "too_fast", "pair": "too_fast,unverified_pair",
                "burst_pair": "burst_pair,skew_week"}
    for _ in range(2):
        ratings.hold_skew_week(key, pg_write(pg), datetime.now(timezone.utc))
        assert {r["device_hash"]: r["hold_reasons"]
                for r in rows(pg, "SELECT device_hash, hold_reasons FROM survey_ratings")} == expected
    agent = {r["device_hash"]: (r["agent_decision"], r["agent_reason"], r["agent_reviewed_at"])
             for r in rows(pg, "SELECT device_hash, agent_decision, agent_reason, agent_reviewed_at FROM survey_ratings")}
    # The escalate predates skew_week, so it is cleared for a re-review; the reject stays.
    assert agent["escalated"] == (None, None, None)
    assert agent["rejected"] == ("reject", "x", reviewed)
    assert {r["device_hash"]: r["updated_at"]
            for r in rows(pg, "SELECT device_hash, updated_at FROM survey_ratings")} == before


def test_hold_matches_holds_back_only_rows_sharing_the_copys_device_or_network(pg):
    import ratings

    for device, ip, prefix in [("mine", "x", "x"), ("ip", "ip1", "x"), ("net", "y", "net1"), ("stranger", "z", "z")]:
        insert(pg, device, "jane-doe", None, "CS2500", None)
        with pg.cursor() as cur:
            cur.execute("UPDATE survey_ratings SET ip_hash = %s, ip_prefix_hash = %s WHERE device_hash = %s",
                        (ip, prefix, device))
    pg.commit()
    ids = [r["id"] for r in rows(pg, "SELECT id::text AS id FROM survey_ratings")]

    def held():
        return sorted(r["device_hash"] for r in rows(
            pg, "SELECT device_hash FROM survey_ratings WHERE status = 'held'"))

    # On a shared network only the device counts: a classmate on campus wifi is no link.
    ratings.hold_matches(ids, "near_duplicate", "mine", "ip1", "net1", "campus", pg_write(pg))
    assert held() == ["mine"]
    ratings.hold_matches(ids, "near_duplicate", "copier", "ip1", "net1", "residential", pg_write(pg))
    assert held() == ["ip", "mine", "net"]


def test_skew_week_leaves_out_the_row_being_edited(pg):
    import ratings
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    truncate(pg, "professors_catalog")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors_catalog (slug, name, name_key, avg_rating) "
                    "VALUES ('jane-doe', 'Jane Doe', 'jane doe', 4.2)")
    for i in range(7):
        insert(pg, f"d{i}", "jane-doe", None, "CS2500", None, rating=1)
    pg.commit()
    key = {"professor_slug": "jane-doe", "pending_professor_id": None,
           "course_code": "CS2500", "pending_course_id": None}
    edited = scalar(pg, "SELECT id::text FROM survey_ratings WHERE device_hash = 'd0'")
    # d0 editing its own rating is still 7 ratings, not 8.
    assert ratings.skew_week(key, 1, True, edited, pg_query_one(pg), now) is False
    assert ratings.skew_week(key, 1, True, None, pg_query_one(pg), now) is True
