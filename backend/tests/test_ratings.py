"""Unit tests for the rating data layer in ratings.py, using a recording fake."""

from datetime import datetime, timedelta, timezone

import ratings

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
KEY = {"professor_slug": "jane-doe", "pending_professor_id": None,
       "course_code": "CS2500", "pending_course_id": None}


class Fake:
    """query_one / query dispatch on a substring of the SQL; write records."""

    def __init__(self, one=None, many=None):
        self.one = one or {}
        self.many = many or {}
        self.calls = []
        self.writes = []

    def query_one(self, sql, params=()):
        self.calls.append((sql, params))
        for needle, row in self.one.items():
            if needle in sql:
                return row
        return None

    def query(self, sql, params=()):
        self.calls.append((sql, params))
        for needle, rows in self.many.items():
            if needle in sql:
                return rows
        return []

    def write(self, sql, params=()):
        self.writes.append((sql, params))


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_term_start():
    assert ratings.term_start(utc(2026, 10, 18)) == utc(2026, 9, 1)
    assert ratings.term_start(utc(2026, 1, 1)) == utc(2026, 1, 1)
    assert ratings.term_start(utc(2026, 4, 30)) == utc(2026, 1, 1)
    assert ratings.term_start(utc(2026, 5, 1)) == utc(2026, 5, 1)


def test_counter_hidden_below_25():
    f = Fake(one={"count(*)": {"cnt": 24}})
    assert ratings.huskies_this_term(f.query_one, NOW) is None
    f = Fake(one={"count(*)": {"cnt": 25}})
    assert ratings.huskies_this_term(f.query_one, NOW) == 25
    assert f.calls[0][1] == (ratings.term_start(NOW),)


class PendingFake(Fake):
    """The pending row is whichever insert landed first, like the partial unique index."""

    def query_one(self, sql, params=()):
        self.calls.append((sql, params))
        return {"id": self.writes[0][1][0]} if self.writes else None


def test_pending_professor_reuses_a_pending_row_with_the_same_name_key():
    f = PendingFake()
    f.writes.append(("INSERT", ("p1",)))
    assert ratings.pending_professor("  Jane   DOE ", "CS", f.query_one, f.write) == ("p1", False)
    assert f.calls[0][1] == ("jane doe",)
    sql, params = f.writes[1]
    assert "ON CONFLICT (name_key) WHERE status = 'pending' DO NOTHING" in sql
    assert params[1:] == ("  Jane   DOE ", "jane doe", "CS")
    f = PendingFake()
    new_id, created = ratings.pending_professor("  Jane   DOE ", "CS", f.query_one, f.write)
    assert created is True and f.writes[0][1][0] == new_id


def test_pending_professor_key_matches_professors_name_key():
    f = PendingFake()
    ratings.pending_professor("Ana Muñoz", None, f.query_one, f.write)
    assert f.writes[0][1][2] == "ana munoz"


def test_pending_course_reuses_a_pending_row_with_the_same_code():
    f = PendingFake()
    f.writes.append(("INSERT", ("c1",)))
    assert ratings.pending_course("CS9999", "New", f.query_one, f.write) == ("c1", False)
    assert "ON CONFLICT (code) WHERE status = 'pending' DO NOTHING" in f.writes[1][0]
    f = PendingFake()
    new_id, created = ratings.pending_course("CS9999", "New", f.query_one, f.write)
    assert created is True and f.writes[0][1] == (new_id, "CS9999", "New")


def test_course_exists_counts_codes_approved_since_the_last_pipeline_run():
    f = Fake(one={"status = 'approved'": {"x": 1}})
    assert ratings.course_exists("ZZ9999", f.query_one) is True
    assert len(f.calls) == 3
    assert ratings.course_exists("ZZ9999", Fake().query_one) is False


def test_rating_key_nulls_the_resolved_side_of_a_pending_pair():
    clean = {"professor_slug": "jane-doe", "course_code": "CS2500"}
    assert ratings.rating_key(clean, None, None) == KEY
    assert ratings.rating_key(clean, "pp", "pc") == {
        "professor_slug": None, "pending_professor_id": "pp",
        "course_code": None, "pending_course_id": "pc"}


def test_existing_rating_matches_all_four_key_columns_null_safely():
    f = Fake(one={"survey_ratings": {"id": "r1", "status": "held", "hold_reasons": "too_fast"}})
    assert ratings.existing_rating("d1", KEY, f.query_one)["hold_reasons"] == "too_fast"
    sql, params = f.calls[0]
    assert sql.count("IS NOT DISTINCT FROM") == 4
    assert params == ("d1", "jane-doe", None, "CS2500", None)


def test_device_seen():
    f = Fake(one={"survey_ratings": {"x": 1}})
    assert ratings.device_seen("d1", f.query_one) is True
    sql, params = f.calls[0]
    assert "WHERE device_hash = %s" in sql and params == ("d1",)
    assert ratings.device_seen("d1", Fake().query_one) is False


def test_duplicate_comment():
    f = Fake(one={"comment_hash": {"x": 1}})
    assert ratings.duplicate_comment(None, "r1", f.query_one) is False
    assert f.calls == []
    assert ratings.duplicate_comment("h", "r1", f.query_one) is True
    assert ratings.duplicate_comment("h", "r1", Fake().query_one) is False


def test_save_is_one_upsert_that_keeps_holds():
    row = {c: None for c in ratings.RATING_COLUMNS if c != "id"}
    f = Fake()
    assert ratings.save_rating(row, {"id": "r1", "status": "held", "hold_reasons": "x"}, f.write) == "r1"
    assert len(f.writes) == 1
    sql, params = f.writes[0]
    assert ("ON CONFLICT (device_hash, professor_slug, pending_professor_id, course_code, "
            "pending_course_id) DO UPDATE") in sql
    assert "WHEN survey_ratings.status = 'held' THEN 'held'" in sql
    assert "updated_at = now()" in sql
    assert "new_device = EXCLUDED" not in sql  # an edit keeps the row's first new_device
    assert sql.count("%s") == len(params) == len(ratings.RATING_COLUMNS)
    f = Fake()
    assert ratings.save_rating(row, None, f.write) == f.writes[0][1][0]


def test_resubmitting_a_held_row_keeps_its_old_hold_reasons():
    col = 1 + ratings._INSERT_COLUMNS.index("hold_reasons")
    row = {c: None for c in ratings.RATING_COLUMNS if c != "id"}

    def saved(existing, reasons):
        f = Fake()
        ratings.save_rating({**row, "hold_reasons": reasons}, existing, f.write)
        return f.writes[0][1][col]
    held = {"id": "r1", "status": "held", "hold_reasons": "burst_ip,duplicate_comment"}
    assert saved(held, "too_fast,duplicate_comment") == "burst_ip,duplicate_comment,too_fast"
    assert saved(held, None) is None  # the upsert keeps the old reasons itself
    assert saved({**held, "status": "accepted"}, "too_fast") == "too_fast"
    assert saved(None, "too_fast") == "too_fast"


def test_burst_ip_skipped_on_campus_and_relay():
    f = Fake(one={"ip_hash": {"cnt": 50}})
    for net in ("campus", "relay"):
        assert ratings.burst_reasons(KEY, "ip", "pre", net, f.query_one, NOW) == []
    assert ratings.burst_reasons(KEY, "ip", "pre", "other", f.query_one, NOW) == ["burst_ip"]


def test_pair_burst_needs_both_count_and_pace():
    def reasons(hour, month):
        f = Fake(one={"new_device = true": {"hour": hour, "month": month}})
        return ratings.burst_reasons(KEY, None, None, "other", f.query_one, NOW)
    assert reasons(5, 720) == ["burst_pair"]
    assert reasons(5, 7200) == []
    assert reasons(4, 720) == []


def test_hold_burst_holds_recent_accepted_rows_per_tripped_trigger():
    f = Fake()
    ratings.hold_burst(["burst_pair", "burst_ip"], KEY, "ip", "pre", f.write, NOW)
    assert len(f.writes) == 2
    for sql, params in f.writes:
        assert "status = 'held'" in sql and "status = 'accepted'" in sql
        assert "hold_reasons IS NULL" in sql  # leaves reviewer-approved rows alone
        assert params[1] == NOW - timedelta(hours=1)
    assert f.writes[0][1][0] == "burst_pair" and f.writes[1][1][2] == "ip"
    # burst_pair counts only new-device rows, so it holds only those.
    assert "new_device = true" in f.writes[0][0] and "new_device" not in f.writes[1][0]


def test_professor_context_returns_earlier_answers():
    many = {"FROM survey_ratings": [
        {"course_code": "CS3500", "name": "Object-Oriented Design", "term_label": "Fall 2025",
         "rating": 4, "hours": "5-7", "grade": "A-", "comment": "Projects take time."},
        {"course_code": "CS4973", "name": None, "term_label": None,
         "rating": 5, "hours": "8-10", "grade": None, "comment": None},
    ]}
    f = Fake(many=many)
    assert ratings.professor_context("jane-doe", "d1", f.query) == {"ratedCourses": [
        {"code": "CS3500", "name": "Object-Oriented Design", "term": "Fall 2025",
         "rating": 4, "hours": "5-7", "grade": "A-", "comment": "Projects take time."},
        {"code": "CS4973", "name": None, "term": None,
         "rating": 5, "hours": "8-10", "grade": None, "comment": ""}]}
    sql, params = f.calls[0]
    assert "LEFT JOIN course_catalog" in sql and params == ("d1", "jane-doe")
    assert len(f.calls) == 1
    assert ratings.professor_context("jane-doe", None, Fake(many=many).query) == {"ratedCourses": []}


def test_purge_clears_hashes_older_than_30_days():
    f = Fake()
    ratings.purge_ip_hashes(f.write, NOW)
    assert f.writes[0][1] == (NOW - timedelta(days=30),)
