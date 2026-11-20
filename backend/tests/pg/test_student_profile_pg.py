"""student_profiles reads and upserts against real PostgreSQL."""

import pytest

from student_profile import profile_status, rater_grad_year, record_view, save_profile
from tests.pg.pgutil import query_fn, rows, truncate


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
    save_profile("u1", {"grad_year": 2028, "majors": ["A, BS"], "minors": []}, write)
    first = rows(pg, "SELECT * FROM student_profiles")[0]
    with pg.cursor() as cur:
        cur.execute("UPDATE student_profiles SET tracking_opt_out = true")
    pg.commit()
    save_profile("u1", {"grad_year": 2029, "majors": ["B, BS", "other"], "minors": ["C, Minor"]}, write)
    got = rows(pg, "SELECT * FROM student_profiles")
    assert len(got) == 1
    assert got[0]["majors"] == ["B, BS", "other"] and got[0]["minors"] == ["C, Minor"]
    assert got[0]["grad_year"] == 2029
    assert got[0]["tracking_opt_out"] is True
    assert got[0]["updated_at"] > first["updated_at"]


def test_profile_status_reads_the_row(pg):
    q1 = one(pg)
    assert profile_status("u1", q1) == {"exists": False, "optedOut": False}
    save_profile("u1", {"grad_year": None, "majors": [], "minors": []}, run_write(pg))
    assert profile_status("u1", q1) == {"exists": True, "optedOut": False}
    with pg.cursor() as cur:
        cur.execute("UPDATE student_profiles SET tracking_opt_out = true")
    pg.commit()
    assert profile_status("u1", q1) == {"exists": True, "optedOut": True}


def test_record_view_inserts_one_row(pg):
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors_catalog (slug, name, name_key) VALUES ('alice-smith', 'Alice Smith', 'alice smith')")
    pg.commit()
    write = run_write(pg)
    save_profile("u1", {"grad_year": 2028, "majors": ["A, BS"], "minors": []}, write)
    view = {"item_type": "professor", "item_key": "alice-smith", "visible_seconds": 42,
            "reached_section": True, "course_filter": None}
    assert record_view("u1", view, one(pg), write) == "ok"
    got = rows(pg, "SELECT * FROM page_views")
    assert len(got) == 1
    assert (got[0]["user_sub"], got[0]["item_type"], got[0]["item_key"]) == ("u1", "professor", "alice-smith")
    assert got[0]["visible_seconds"] == 42 and got[0]["reached_section"] is True
    assert got[0]["course_filter"] is None and got[0]["viewed_at"] is not None


def test_rater_grad_year_is_none_when_opted_out_or_grad(pg):
    write, q = run_write(pg), one(pg)
    assert rater_grad_year(None, q) is None
    assert rater_grad_year("nobody", q) is None
    save_profile("normal", {"grad_year": 2028, "majors": ["A, BS"], "minors": []}, write)
    save_profile("grad", {"grad_year": None, "majors": [], "minors": []}, write)
    save_profile("out", {"grad_year": 2027, "majors": ["A, BS"], "minors": []}, write)
    with pg.cursor() as cur:
        cur.execute("UPDATE student_profiles SET tracking_opt_out = true WHERE user_sub = 'out'")
    pg.commit()
    assert rater_grad_year("normal", q) == 2028
    assert rater_grad_year("grad", q) is None
    assert rater_grad_year("out", q) is None


def test_edit_keeps_rater_grad_year_when_profile_is_gone(pg):
    import ratings

    def submit(year):
        row = {c: None for c in ratings.RATING_COLUMNS if c != "id"}
        row.update(professor_slug="jane-doe", course_code="CS2500", rating=5, hours="3-4",
                   status="accepted", account_hash="a1", device_hash="d1", new_device=False,
                   network_type="unknown", collection="turnstile+account", rater_grad_year=year)
        ratings.save_rating(row, None, run_write(pg))
        return rows(pg, "SELECT rater_grad_year FROM survey_ratings")

    assert [r["rater_grad_year"] for r in submit(2028)] == [2028]
    assert [r["rater_grad_year"] for r in submit(None)] == [2028]
    assert [r["rater_grad_year"] for r in submit(2029)] == [2029]
