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


def test_a_new_comment_waits_for_review_and_an_unchanged_one_keeps_its_approval():
    col = 1 + ratings._INSERT_COLUMNS.index("comment_status")
    row = {c: None for c in ratings.RATING_COLUMNS if c != "id"}

    def saved(**kw):
        f = Fake()
        ratings.save_rating({**row, **kw}, None, f.write)
        return f.writes[0]
    assert saved(comment="Hard but fair", comment_status="approved")[1][col] == "pending"
    assert saved(comment=None)[1][col] is None
    sql = saved()[0]
    assert "comment_status = EXCLUDED" not in sql
    assert ("comment_status = CASE WHEN EXCLUDED.comment IS NULL THEN NULL "
            "WHEN EXCLUDED.comment = survey_ratings.comment THEN survey_ratings.comment_status "
            "ELSE 'pending' END") in sql


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


def test_moderation_budget_per_device_per_ip_and_on_shared_networks():
    seen = []

    def counts(device=0, ip=0, shared=0):
        return lambda sql, params: seen.append((sql, params)) or {"device": device, "ip": ip, "shared": shared}

    assert ratings.moderation_budget_left("d", "i", False, counts(device=2, ip=9), NOW) is True
    assert ratings.moderation_budget_left("d", "i", False, counts(device=3), NOW) is False
    assert ratings.moderation_budget_left("d", "i", False, counts(ip=10), NOW) is False
    # Shared networks: the per-IP count doesn't apply, the total for all of them does.
    assert ratings.moderation_budget_left("d", "i", True, counts(ip=50, shared=99), NOW) is True
    assert ratings.moderation_budget_left("d", "i", True, counts(shared=100), NOW) is False
    assert ratings.moderation_budget_left("d", "i", True, counts(device=3), NOW) is False
    sql, params = seen[0]
    # Only submit calls count, over a rolling day.
    assert "source = 'submit'" in sql and params == ("d", "i", NOW - timedelta(days=1))


def test_record_moderation_call_keeps_no_text_or_rating_id():
    writes = []
    ratings.record_moderation_call("queue", "allow", None, None, False,
                                   lambda sql, params: writes.append((sql, params)), NOW)
    ((sql, params),) = writes
    assert sql.startswith("INSERT INTO moderation_calls") and params[1:] == (NOW, "queue", "allow", None, None, False)
    assert "comment" not in sql and "rating" not in sql


def test_the_upsert_keeps_the_check_while_the_text_is_unchanged():
    for column in ratings.CHECK_COLUMNS:
        assert (f"{column} = CASE WHEN EXCLUDED.comment IS NOT DISTINCT FROM survey_ratings.comment "
                f"THEN survey_ratings.{column} ELSE EXCLUDED.{column} END") in ratings._UPSERT_SQL
