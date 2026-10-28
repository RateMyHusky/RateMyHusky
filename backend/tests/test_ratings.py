"""Unit tests for the rating data layer in ratings.py, using a recording fake."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

import ratings
from tests.razzaq_bomb import BOMB

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
LECTURES = next(r["comment"] for r in BOMB if r["comment"].startswith("Lecutres"))
SERIOUSLY = next(r["comment"] for r in BOMB if r["comment"].startswith("Seriously"))
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
    # An approved row keeps its reasons too, so an edit doesn't bring it back into the counts.
    approved = {**held, "status": "accepted"}
    assert saved(approved, "too_fast") == "burst_ip,duplicate_comment,too_fast"
    assert saved({**approved, "hold_reasons": None}, "too_fast") == "too_fast"
    assert saved(None, "too_fast") == "too_fast"


def test_a_clean_edit_keeps_the_rows_hold_reasons():
    # A reviewer approved a held rating (accepted, reasons kept); a clean edit mustn't clear them.
    sql = ratings._UPSERT_SQL
    assert "hold_reasons = COALESCE(EXCLUDED.hold_reasons, survey_ratings.hold_reasons)" in sql


def test_burst_ip_skipped_on_campus_and_relay():
    f = Fake(one={"ip_hash": {"cnt": 50}})
    for net in ("campus", "relay"):
        assert ratings.burst_reasons(KEY, "ip", "pre", net, f.query_one, NOW) == []
    assert ratings.burst_reasons(KEY, "ip", "pre", "other", f.query_one, NOW) == ["burst_ip"]


PROF_COUNT = "AS pair_month FROM survey_ratings"


def prof_row(**counts):
    return {"hour": 0, "month": 0, "day": 0, "pair_hour": 0, "pair_month": 0, **counts}


def test_pair_burst_needs_both_count_and_pace():
    def reasons(hour, month):
        f = Fake(one={PROF_COUNT: prof_row(pair_hour=hour, pair_month=month)})
        return ratings.burst_reasons(KEY, None, None, "other", f.query_one, NOW)
    assert reasons(5, 720) == ["burst_pair"]
    assert reasons(5, 7200) == []
    assert reasons(4, 720) == []


def test_professor_burst_needs_both_count_and_pace_on_every_network():
    def reasons(hour, month, net="campus"):
        f = Fake(one={PROF_COUNT: prof_row(hour=hour, month=month)})
        return ratings.burst_reasons(KEY, None, None, net, f.query_one, NOW)
    assert reasons(10, 720) == ["burst_prof"]
    assert reasons(10, 720, "relay") == ["burst_prof"]
    assert reasons(10, 7200) == []
    assert reasons(9, 720) == []


def test_professor_burst_counts_every_device_and_course():
    # Seasoned devices and invented course codes both dodge the pair count.
    f = Fake()
    ratings.burst_reasons(KEY, None, None, "other", f.query_one, NOW)
    (sql, params), = [c for c in f.calls if PROF_COUNT in c[0]]
    where = sql.split(" FROM survey_ratings WHERE ")[1]
    assert "new_device" not in where and "course_code" not in where
    assert params == (NOW - timedelta(hours=1), NOW - timedelta(days=1), NOW - timedelta(hours=1),
                      "CS2500", None, "CS2500", None, NOW - timedelta(days=30), "jane-doe", None)


def test_every_burst_window_reads_updated_at():
    # An edit keeps created_at, so a wave of edits to old ratings would count nowhere.
    f = Fake()
    ratings.burst_reasons(KEY, "ip", "pre", "other", f.query_one, NOW)
    ratings.hold_burst(list(ratings._BURST_REASONS), KEY, "ip", "pre", f.write, NOW)
    for sql, _ in f.calls + f.writes:
        assert "created_at" not in sql and "updated_at >= %s" in sql


def test_hold_burst_holds_the_professors_recent_rows_from_every_device():
    f = Fake()
    ratings.hold_burst(["burst_prof"], KEY, "ip", "pre", f.write, NOW)
    (sql, params), = f.writes
    assert "status = 'accepted'" in sql and "new_device" not in sql and "course_code" not in sql
    assert params == ("burst_prof", NOW - timedelta(hours=1), "jane-doe", None)


def test_pair_taught_is_one_query_over_banner_rmp_and_approved_ratings():
    f = Fake(one={"AS taught": {"taught": True}})
    assert ratings.pair_taught("jane-doe", "CS2500", f.query_one)
    (sql, params), = f.calls
    assert "banner_course_instructors" in sql and "source = 'rmp'" in sql
    # A reviewer approving an unverified_pair hold vouches for the pair: approval keeps the reason.
    assert "status = 'accepted'" in sql and "ARRAY['unverified_pair']" in sql
    assert params == ("CS2500", "jane-doe") * 3
    assert not ratings.pair_taught("jane-doe", "CS2500", Fake(one={"AS taught": {"taught": False}}).query_one)


COURSE_COUNT = "WHERE updated_at >= %s AND course_code"


def test_course_burst_needs_both_count_and_pace_on_every_network():
    def reasons(hour, month, net="campus"):
        f = Fake(one={COURSE_COUNT: {"hour": hour, "month": month}})
        return ratings.burst_reasons(KEY, None, None, net, f.query_one, NOW)
    assert reasons(20, 720) == ["burst_course"]
    assert reasons(20, 720, "relay") == ["burst_course"]
    assert reasons(20, 7200) == []
    assert reasons(19, 720) == []


def test_course_burst_counts_every_professor_and_device():
    # Spreading one course's ratings over many professors dodges the pair and professor counts.
    f = Fake()
    ratings.burst_reasons(KEY, None, None, "other", f.query_one, NOW)
    (sql, params), = [c for c in f.calls if COURSE_COUNT in c[0]]
    assert "new_device" not in sql and "professor_slug" not in sql
    assert params[2:] == ("CS2500", None)


def test_professor_daily_cap_ignores_pace():
    # A steady drip raises its own hourly limit through the pace factor; this cap has none.
    def reasons(day):
        f = Fake(one={PROF_COUNT: prof_row(day=day, month=10000)})
        return ratings.burst_reasons(KEY, None, None, "campus", f.query_one, NOW)
    assert reasons(30) == ["burst_prof_day"]
    assert reasons(29) == []


PAUSE = "WHERE status = 'held' AND updated_at >= %s"


def test_a_held_burst_pauses_new_ratings_for_72_hours():
    f = Fake(one={PAUSE: {"x": 1}})
    assert ratings.burst_reasons(KEY, None, None, "campus", f.query_one, NOW) == ["burst_pause"]
    (sql, params), = [c for c in f.calls if PAUSE in c[0]]
    assert params[0] == NOW - timedelta(hours=72)
    assert ratings.burst_reasons(KEY, None, None, "campus", Fake().query_one, NOW) == []


def test_hold_burst_holds_the_professors_day_and_the_courses_hour():
    f = Fake()
    ratings.hold_burst(["burst_course", "burst_prof_day", "burst_pause"], KEY, "ip", "pre", f.write, NOW)
    (day_sql, day_params), (course_sql, course_params) = f.writes  # burst_pause holds only the new rating
    assert "course_code" not in day_sql
    assert day_params == ("burst_prof_day", NOW - timedelta(days=1), "jane-doe", None)
    assert "professor_slug" not in course_sql.split("RETURNING")[0]
    assert course_params == ("burst_course", NOW - timedelta(hours=1), "CS2500", None)


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


def test_hold_burst_returns_the_professors_whose_rows_it_held():
    returned = iter([[{"professor_slug": "alice-smith"}, {"professor_slug": None}],
                     [{"professor_slug": "bob-jones"}, {"professor_slug": "alice-smith"}]])
    held = ratings.hold_burst(["burst_ip", "burst_prefix"], KEY, "ip", "pre", lambda sql, params: next(returned), NOW)
    assert held == {"alice-smith", "bob-jones"}   # a pending-professor row has no page to drop


def test_hold_burst_with_nothing_held_returns_no_professors():
    f = Fake()
    assert ratings.hold_burst(["burst_ip"], KEY, "ip", "pre", f.write, NOW) == set()
    assert "RETURNING professor_slug" in f.writes[0][0]


def test_professor_context_returns_earlier_answers():
    many = {"FROM survey_ratings": [
        {"code": "CS3500", "name": "Object-Oriented Design", "pending": False, "term_label": "Fall 2025",
         "rating": 4, "difficulty": 4, "hours": "5-7", "grade": "A-", "comment": "Projects take time."},
        {"code": "CS4973", "name": None, "pending": False, "term_label": None,
         "rating": 5, "difficulty": None, "hours": "8-10", "grade": None, "comment": None},
        {"code": "CS4999", "name": "Applied ML", "pending": True, "term_label": "Fall 2025",
         "rating": 3, "difficulty": 2, "hours": "3-4", "grade": None, "comment": None},
    ]}
    f = Fake(many=many)
    assert ratings.professor_context("jane-doe", "d1", f.query) == {"ratedCourses": [
        {"code": "CS3500", "name": "Object-Oriented Design", "pending": False, "term": "Fall 2025",
         "rating": 4, "difficulty": 4, "hours": "5-7", "grade": "A-", "comment": "Projects take time."},
        {"code": "CS4973", "name": None, "pending": False, "term": None,
         "rating": 5, "difficulty": None, "hours": "8-10", "grade": None, "comment": ""},
        {"code": "CS4999", "name": "Applied ML", "pending": True, "term": "Fall 2025",
         "rating": 3, "difficulty": 2, "hours": "3-4", "grade": None, "comment": ""}]}
    sql, params = f.calls[0]
    assert "LEFT JOIN course_catalog" in sql and params == ("d1", "jane-doe")
    # Pending courses come from their review row, and held ratings count, so there's no status filter on r.
    assert "pc.status = 'pending'" in sql and "r.status" not in sql
    assert len(f.calls) == 1
    f2 = Fake(many=many)
    assert ratings.professor_context("jane-doe", None, f2.query) == {"ratedCourses": []}
    assert len(f2.calls) == 0


def test_purge_clears_hashes_older_than_30_days():
    f = Fake()
    ratings.purge_ip_hashes(f.write, NOW)
    assert f.writes[0][1] == (NOW - timedelta(days=30),)


def test_near_duplicate_ids_returns_close_comments_on_the_professor():
    f = Fake(many={"FROM survey_ratings": [
        {"id": "r1", "comment": LECTURES},
        {"id": "r2", "comment": "Totally different words about a fine class overall."}]})
    assert ratings.near_duplicate_ids(SERIOUSLY, KEY, None, f.query, NOW) == ["r1"]
    (sql, params), = f.calls
    assert "professor_slug IS NOT DISTINCT FROM" in sql and "course_code" not in sql
    assert params == ("jane-doe", None, NOW - timedelta(days=30), None)


def test_near_duplicate_skips_short_comments_without_a_query():
    f = Fake()
    assert ratings.near_duplicate_ids("Great class!", KEY, None, f.query, NOW) == []
    assert f.calls == []


def test_near_duplicate_excludes_the_edited_row():
    f = Fake()
    ratings.near_duplicate_ids(SERIOUSLY, KEY, "r1", f.query, NOW)
    assert f.calls[0][1][-1] == "r1"


def test_hold_matches_holds_accepted_and_appends_to_held():
    f = Fake()
    ratings.hold_matches(["r1"], "near_duplicate", f.write)
    (hold_sql, hold_params), (append_sql, append_params) = f.writes
    assert "SET status = 'held', hold_reasons = %s" in hold_sql
    assert "status = 'accepted' AND hold_reasons IS NULL AND id::text = ANY(%s)" in hold_sql
    assert hold_params == ("near_duplicate", ["r1"])
    assert "status = 'held'" in append_sql and "hold_reasons = hold_reasons || %s" in append_sql
    assert append_params[0] == ",near_duplicate" and ["r1"] in append_params


def test_hold_matches_with_no_ids_writes_nothing():
    f = Fake()
    ratings.hold_matches([], "near_duplicate", f.write)
    assert f.writes == []


def _skew(new_device=True, rating=1, key=KEY, week=None, prior=None):
    week = {"n": 7, "total": 10, "squares": 16} if week is None else week
    f = Fake(one={"survey_ratings": week, "professors_catalog": {"avg_rating": 4.0} if prior is None else prior})
    return ratings.skew_week(key, rating, new_device, f.query_one, NOW), f


def test_skew_week_trips_on_eight_low_uniform_ratings():
    assert _skew()[0] is True


def test_skew_week_accepts_decimal_sums_from_postgres():
    # sum(bigint) comes back as Decimal; the prior is a float
    week = {"n": 7, "total": Decimal(10), "squares": Decimal(16)}
    assert _skew(week=week, prior={"avg_rating": 4.0})[0] is True


def test_skew_week_needs_eight_including_the_new_one():
    assert _skew(week={"n": 6, "total": 9, "squares": 15})[0] is False


def test_skew_week_needs_a_drop_of_one_and_a_half():
    # mean 2.0 against a prior of 3.0
    assert _skew(rating=2, week={"n": 7, "total": 14, "squares": 28}, prior={"avg_rating": 3.0})[0] is False


def test_skew_week_needs_low_spread():
    # 1,1,1,1,5,1,1 plus the new 1: mean 1.5, pstdev about 1.32
    assert _skew(week={"n": 7, "total": 11, "squares": 31})[0] is False


def test_skew_week_ignores_returning_devices_pending_and_unrated_professors():
    ok, f = _skew(new_device=False)
    assert ok is False and f.calls == []
    ok, f = _skew(key={**KEY, "professor_slug": None, "pending_professor_id": "p1"})
    assert ok is False and f.calls == []
    assert _skew(prior={"avg_rating": None})[0] is False
    f = Fake(one={"survey_ratings": {"n": 7, "total": 10, "squares": 16}})
    assert ratings.skew_week(KEY, 1, True, f.query_one, NOW) is False


def test_skew_week_sql_counts_new_devices_and_skips_approvals():
    _, f = _skew()
    sql, params = f.calls[0]
    assert "new_device = true" in sql and "created_at >= %s" in sql
    assert "NOT (status = 'accepted' AND hold_reasons IS NOT NULL)" in sql
    assert NOW - timedelta(days=7) in params


def test_hold_skew_week_holds_the_unreviewed_new_device_week():
    f = Fake()
    ratings.hold_skew_week(KEY, f.write, NOW)
    (sql, params), = f.writes
    assert "SET status = 'held', hold_reasons = 'skew_week'" in sql
    assert "status = 'accepted' AND hold_reasons IS NULL AND new_device = true" in sql
    assert params == (NOW - timedelta(days=7), "jane-doe", None)


def test_flagged_matches_a_device_or_a_recent_ip():
    f = Fake(one={"FROM rating_flags": {"x": 1}})
    assert ratings.flagged("d", "i", "other", f.query_one, NOW) is True
    (sql, params), = f.calls
    assert "kind = 'device' AND value_hash = %s" in sql
    assert "kind = 'ip' AND value_hash = %s AND created_at >= %s" in sql
    assert params == ("d", "i", NOW - timedelta(days=30))
    assert ratings.flagged("d", "i", "other", Fake().query_one, NOW) is False


@pytest.mark.parametrize("network, ip_hash", [("campus", "i"), ("relay", "i"), ("mobile", "i"), ("other", None)])
def test_flagged_skips_the_ip_on_campus_relay_mobile_or_no_hash(network, ip_hash):
    f = Fake()
    ratings.flagged("d", ip_hash, network, f.query_one, NOW)
    (sql, params), = f.calls
    assert "'ip'" not in sql and params == ("d",)


def test_purge_also_drops_expired_ip_flags():
    f = Fake()
    ratings.purge_ip_hashes(f.write, NOW)
    cutoff = NOW - timedelta(days=30)
    assert f.writes[1] == ("DELETE FROM rating_flags WHERE kind = 'ip' AND created_at < %s", (cutoff,))
