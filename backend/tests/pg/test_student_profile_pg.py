"""student_profiles reads and upserts against real PostgreSQL."""

import pytest

from student_profile import profile_status, save_profile
from tests.pg.pgutil import query_fn, rows, truncate


@pytest.fixture(autouse=True)
def clean(pg):
    truncate(pg, "student_profiles")


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
