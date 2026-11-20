"""student_profiles reads and upserts against real PostgreSQL."""

import os
import threading

import psycopg2
import pytest

os.environ.setdefault("ORACLE_DATABASE_URL", "postgresql://stub")   # rag.clear_ask_strikes needs it at import

import rating_identity
from rag.clear_ask_strikes import opt_out, purge_account
from student_profile import profile_status, rater_profile, record_view, save_profile
from tests.pg.pgutil import query_fn, rows, scalar, truncate

SECRET = "rating-secret-0123456789abcdefghijklmnop"  # gitleaks:allow
def hv(sub):
    return rating_identity.keyed_hash(SECRET, "viewer", sub)


VIEWER = hv("u1")
VIEW = {"item_type": "professor", "item_key": "alice-smith", "visible_seconds": 42,
        "reached_section": True, "course_filter": None}


@pytest.fixture(autouse=True)
def clean(pg):
    truncate(pg, "student_profiles", "page_views", "professors_catalog", "survey_ratings")


def run_write(pg):
    def write(sql, params=None):
        with pg.cursor() as cur:
            cur.execute(sql, params or ())
        pg.commit()
    return write


def one(pg):
    q = query_fn(pg)
    return lambda sql, params=None: (q(sql, params) or [None])[0]


def test_save_profile_upserts_and_keeps_opt_out(pg):
    write = run_write(pg)
    save_profile(hv("u1"), {"level": "undergrad", "grad_year": 2028, "majors": ["A, BS"], "minors": []}, write)
    first = rows(pg, "SELECT * FROM student_profiles")[0]
    with pg.cursor() as cur:
        cur.execute("UPDATE student_profiles SET tracking_opt_out = true")
    pg.commit()
    save_profile(hv("u1"), {"level": "undergrad", "grad_year": 2029, "majors": ["B, BS", "other"], "minors": ["C, Minor"]}, write)
    got = rows(pg, "SELECT * FROM student_profiles")
    assert len(got) == 1
    assert got[0]["majors"] == ["B, BS", "other"] and got[0]["minors"] == ["C, Minor"]
    assert got[0]["grad_year"] == 2029 and got[0]["level"] == "undergrad"
    assert got[0]["tracking_opt_out"] is True
    assert got[0]["updated_at"] > first["updated_at"]


def test_profile_status_reads_the_row(pg):
    q1 = one(pg)
    assert profile_status(hv("u1"), q1) == {"exists": False, "optedOut": False}
    save_profile(hv("u1"), {"level": "grad", "grad_year": None, "majors": [], "minors": []}, run_write(pg))
    assert profile_status(hv("u1"), q1) == {"exists": True, "optedOut": False}
    with pg.cursor() as cur:
        cur.execute("UPDATE student_profiles SET tracking_opt_out = true")
    pg.commit()
    assert profile_status(hv("u1"), q1) == {"exists": True, "optedOut": True}


def test_record_view_inserts_one_row(pg):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors_catalog (slug, name, name_key) VALUES ('alice-smith', 'Alice Smith', 'alice smith')")
    pg.commit()
    write = run_write(pg)
    save_profile(hv("u1"), {"level": "undergrad", "grad_year": 2028, "majors": ["A, BS"], "minors": []}, write)
    assert record_view(VIEWER, VIEW, one(pg), write) == "ok"
    got = rows(pg, "SELECT * FROM page_views")
    assert len(got) == 1
    assert (got[0]["viewer_hash"], got[0]["item_type"], got[0]["item_key"]) == (VIEWER, "professor", "alice-smith")
    assert "user_sub" not in got[0] and "u1" not in {str(v) for v in got[0].values()}
    prof = rows(pg, "SELECT * FROM student_profiles")[0]   # the profile is keyed by the same hash, never the sub
    assert prof["viewer_hash"] == VIEWER and "user_sub" not in prof and "u1" not in {str(v) for v in prof.values()}
    assert VIEWER != rating_identity.keyed_hash(SECRET, "account", "u1")
    assert got[0]["visible_seconds"] == 42 and got[0]["reached_section"] is True
    assert got[0]["course_filter"] is None and got[0]["viewed_at"] is not None


def test_rater_profile_by_profile_kind(pg):
    write, q = run_write(pg), one(pg)
    assert rater_profile(None, q) == (None, None)
    assert rater_profile(hv("nobody"), q) == (None, None)
    save_profile(hv("normal"), {"level": "undergrad", "grad_year": 2028, "majors": ["A, BS"], "minors": []}, write)
    save_profile(hv("grad"), {"level": "grad", "grad_year": None, "majors": [], "minors": []}, write)
    save_profile(hv("out"), {"level": "undergrad", "grad_year": 2027, "majors": ["A, BS"], "minors": []}, write)
    with pg.cursor() as cur:
        cur.execute("UPDATE student_profiles SET tracking_opt_out = true WHERE viewer_hash = %s", (hv("out"),))
        # what rag/clear_ask_strikes.py opt_out inserts for an account with no profile
        cur.execute("INSERT INTO student_profiles (viewer_hash, majors, tracking_opt_out) VALUES (%s, '{}', true)",
                    (hv("stub"),))
    pg.commit()
    assert rater_profile(hv("normal"), q) == ("undergrad", 2028)
    assert rater_profile(hv("grad"), q) == ("grad", None)
    assert rater_profile(hv("out"), q) == (None, None)
    assert rater_profile(hv("stub"), q) == (None, None)


def submit_rating(pg, level, year):
    import ratings
    row = {c: None for c in ratings.RATING_COLUMNS if c != "id"}
    row.update(professor_slug="jane-doe", course_code="CS2500", rating=5, hours="3-4",
               status="accepted", account_hash="a1", device_hash="d1", new_device=False,
               network_type="unknown", collection="turnstile+account", rater_level=level, rater_grad_year=year)
    ratings.save_rating(row, None, run_write(pg))
    return [(r["rater_level"], r["rater_grad_year"])
            for r in rows(pg, "SELECT rater_level, rater_grad_year FROM survey_ratings")]


def test_edit_keeps_rater_level_and_year_when_profile_is_gone(pg):
    assert submit_rating(pg, "undergrad", 2028) == [("undergrad", 2028)]
    assert submit_rating(pg, None, None) == [("undergrad", 2028)]
    assert submit_rating(pg, "undergrad", 2029) == [("undergrad", 2029)]


def test_edit_after_switching_to_grad_clears_the_year(pg):
    assert submit_rating(pg, "undergrad", 2028) == [("undergrad", 2028)]
    assert submit_rating(pg, "grad", None) == [("grad", None)]
    assert submit_rating(pg, None, None) == [("grad", None)]


def test_a_failed_profile_lookup_leaves_the_connection_usable(live_server, pg):
    import psycopg2
    with live_server.app.app_context():
        with pytest.raises(psycopg2.Error):
            live_server.query_one("SELECT 1 FROM table_that_does_not_exist")
        live_server._write("INSERT INTO student_profiles (viewer_hash, level, grad_year, majors) "
                           "VALUES ('x', 'grad', NULL, '{}')")
        assert live_server.query_one("SELECT level FROM student_profiles WHERE viewer_hash = 'x'")["level"] == "grad"


def test_collect_counts(pg):
    import ratings
    from datetime import datetime, timedelta, timezone
    from profile_stats import collect

    write = run_write(pg)
    save_profile(hv("u1"), {"level": "undergrad", "grad_year": 2028, "majors": ["A, BS"], "minors": []}, write)
    save_profile(hv("u2"), {"level": "grad", "grad_year": None, "majors": [], "minors": []}, write)
    save_profile(hv("u3"), {"level": "undergrad", "grad_year": 2027, "majors": ["B, BS"], "minors": []}, write)
    with pg.cursor() as cur:
        cur.execute("UPDATE student_profiles SET tracking_opt_out = true WHERE viewer_hash = %s", (hv("u3"),))
        for sub, kind, key in [("u1", "professor", "alice-smith"), ("u1", "professor", "alice-smith"),
                               ("u2", "course", "CS2500"), ("u2", "professor", "alice-smith")]:
            cur.execute("INSERT INTO page_views (viewer_hash, item_type, item_key, visible_seconds, reached_section)"
                        " VALUES (%s, %s, %s, 5, false)", (hv(sub), kind, key))
    pg.commit()
    for i, (level, year) in enumerate([("undergrad", 2028), ("grad", None), (None, None)]):
        row = {c: None for c in ratings.RATING_COLUMNS if c != "id"}
        row.update(professor_slug="jane-doe", course_code="CS2500", rating=5, hours="3-4",
                   status="accepted", account_hash=f"a{i}", device_hash=f"d{i}", new_device=False,
                   network_type="unknown", collection="turnstile+account", rater_level=level, rater_grad_year=year)
        ratings.save_rating(row, None, write)

    got = collect(query_fn(pg), datetime.now(timezone.utc) - timedelta(days=1))
    assert got["profiles"] == 3 and got["opted_out"] == 1 and got["answered"] == 2
    assert got["by_grad_year"] == {"2028": 1, "grad student": 1}
    assert got["by_major"] == {"A, BS": 1}
    assert (got["views"], got["view_students"], got["view_professors"], got["view_courses"]) == (4, 2, 1, 1)
    assert got["views_per_student"] == 2.0
    assert (got["ratings_undergrad"], got["ratings_grad"], got["ratings_unknown"]) == (1, 1, 1)
    assert got["ratings_by_grad_year"] == {"2028": 1}


def seed_catalog_and_profile(pg):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors_catalog (slug, name, name_key) VALUES ('alice-smith', 'Alice Smith', 'alice smith')")
    pg.commit()
    save_profile(hv("u1"), {"level": "undergrad", "grad_year": 2028, "majors": ["A, BS"], "minors": []}, run_write(pg))


def view_count(pg):
    return scalar(pg, "SELECT count(*) FROM page_views WHERE viewer_hash = %s", (VIEWER,))


def opted_out(pg):
    return scalar(pg, "SELECT tracking_opt_out FROM student_profiles WHERE viewer_hash = %s", (VIEWER,))


def test_opt_out_waits_for_a_view_in_flight_and_then_deletes_it(pg, pg_url):
    seed_catalog_and_profile(pg)
    a = psycopg2.connect(pg_url)
    b = psycopg2.connect(pg_url)
    try:
        # A: record_view's insert, transaction still open, holding the profile row lock
        def write_in_open_transaction(sql, params=None):
            a.cursor().execute(sql, params)
        assert record_view(VIEWER, VIEW, one(pg), write_in_open_transaction) == "ok"
        done = threading.Event()

        def run_opt_out():
            opt_out(b, b.cursor(), "u1", False, SECRET)
            done.set()
        t = threading.Thread(target=run_opt_out)
        t.start()
        assert not done.wait(1.5)   # blocked on A's lock
        a.commit()
        t.join(15)
        assert done.is_set()
        assert view_count(pg) == 0 and opted_out(pg) is True
    finally:
        a.close()
        b.close()


def test_a_view_in_flight_when_the_opt_out_commits_inserts_nothing(pg, pg_url):
    seed_catalog_and_profile(pg)
    b = psycopg2.connect(pg_url)
    try:
        q = one(pg)

        def profile_check_passes_then_the_opt_out_lands(sql, params=None):
            row = q(sql, params)
            if "FROM student_profiles" in sql:
                opt_out(b, b.cursor(), "u1", False, SECRET)   # commits between the check and the insert
            return row
        assert record_view(VIEWER, VIEW, profile_check_passes_then_the_opt_out_lands, run_write(pg)) == "ok"
        assert opted_out(pg) is True and view_count(pg) == 0
    finally:
        b.close()


def test_purge_keeps_an_opted_out_account_opted_out(pg, capsys):
    seed_catalog_and_profile(pg)
    record_view(VIEWER, VIEW, one(pg), run_write(pg))
    other = rating_identity.keyed_hash(SECRET, "viewer", "u2")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO page_views (viewer_hash, item_type, item_key, visible_seconds, reached_section) "
                    "VALUES (%s, 'course', 'CS2500', 5, false)", (other,))
    pg.commit()
    opt_out(pg, pg.cursor(), "u1", False, SECRET)
    purge_account(pg, pg.cursor(), "u1", False, SECRET)
    got = rows(pg, "SELECT viewer_hash, level, majors, tracking_opt_out FROM student_profiles")
    assert got == [{"viewer_hash": VIEWER, "level": None, "majors": [], "tracking_opt_out": True}]
    assert view_count(pg) == 0 and scalar(pg, "SELECT count(*) FROM page_views") == 1   # u2's view stays
    assert record_view(VIEWER, VIEW, one(pg), run_write(pg)) == "ignored"
    assert "opt-out still holds" in capsys.readouterr().out


def test_purge_of_an_account_that_never_opted_out_removes_the_profile(pg):
    seed_catalog_and_profile(pg)
    record_view(VIEWER, VIEW, one(pg), run_write(pg))
    purge_account(pg, pg.cursor(), "u1", False, SECRET)
    assert scalar(pg, "SELECT count(*) FROM student_profiles") == 0 and view_count(pg) == 0
