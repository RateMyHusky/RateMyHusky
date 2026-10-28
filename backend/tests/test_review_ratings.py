"""Unit tests for the review_ratings CLI, using a recording fake cursor."""

import pytest

import review_ratings as rr

PENDING = {"id": "p1", "name": "Jane Doe", "name_key": "jane doe",
           "department": "Computer Science", "status": "pending"}


class FakeCursor:
    """Records execute(sql, params); fetchone/fetchall serve the first canned
    result whose key is a substring of the SQL (an empty list when none match)."""

    def __init__(self, canned=None):
        self.canned = canned or {}
        self.calls = []
        self._rows = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self._rows = next((rows for key, rows in self.canned.items() if key in sql), [])

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def statements(self, prefix):
        return [(s, p) for s, p in self.calls if s.lstrip().startswith(prefix)]


def index_of(cur, fragment):
    return next(i for i, (sql, _) in enumerate(cur.calls) if fragment in sql)


def test_approve_professor_inserts_survey_origin_and_moves_ratings():
    cur = FakeCursor({"FROM survey_pending_professors": [PENDING],
                      "ORDER BY slug": [{"slug": "john-doe"}]})
    summary = rr.approve_professor(cur, "p1")
    (sql, params), = cur.statements("INSERT INTO professors")
    assert "'survey'" in sql
    assert params[:4] == ("jane-doe", "Jane Doe", "jane doe", "Computer Science")
    (sql, params), _ = cur.statements("UPDATE survey_ratings")
    assert "professor_slug = %s" in sql and "pending_professor_id = NULL" in sql
    assert params == ("jane-doe", "p1")
    (sql, params), = cur.statements("UPDATE survey_pending_professors")
    assert "status = 'approved'" in sql and params == ("jane-doe", "p1")
    assert "jane-doe" in summary


def test_approve_professor_twice_raises():
    cur = FakeCursor({"FROM survey_pending_professors": [dict(PENDING, status="approved")]})
    with pytest.raises(rr.ReviewError):
        rr.approve_professor(cur, "p1")
    assert not cur.statements("INSERT") and not cur.statements("UPDATE")


def test_approve_professor_refuses_an_existing_name_key():
    cur = FakeCursor({"FROM survey_pending_professors": [PENDING],
                      "WHERE name_key": [{"slug": "jane-doe"}]})
    with pytest.raises(rr.ReviewError, match="jane-doe"):
        rr.approve_professor(cur, "p1")
    assert not cur.statements("INSERT")


def test_approve_professor_strips_control_characters_from_the_name():
    evil = dict(PENDING, name="Jane[2J Doe")
    cur = FakeCursor({"FROM survey_pending_professors": [evil],
                      "ORDER BY slug": [{"slug": "john-doe"}]})
    assert "" not in rr.approve_professor(cur, "p1")
    cur = FakeCursor({"FROM survey_pending_professors": [evil],
                      "WHERE name_key": [{"slug": "jane-doe"}]})
    with pytest.raises(rr.ReviewError) as e:
        rr.approve_professor(cur, "p1")
    assert "" not in str(e.value)


def test_approve_course_strips_control_characters_from_the_code():
    row = {"id": "c1", "code": "CS[2J1", "name": "X", "status": "pending"}
    cur = FakeCursor({"FROM survey_pending_courses": [row]})
    assert "" not in rr.approve_course(cur, "c1")


@pytest.mark.parametrize("slug", ["Jane-Doe", "jane doe", "jane--doe", "-jane", "jane-", "jane/doe", ""])
def test_approve_professor_rejects_a_malformed_slug(slug):
    cur = FakeCursor({"FROM survey_pending_professors": [PENDING]})
    with pytest.raises(rr.ReviewError, match="slug"):
        rr.approve_professor(cur, "p1", slug)
    assert not cur.statements("INSERT")


def test_merge_keeps_the_newest_rating_per_device_and_course():
    cur = FakeCursor({"FROM survey_pending_professors": [PENDING],
                      "SELECT 1 FROM professors": [{"?column?": 1}]})
    rr.merge_professor(cur, "p1", "jane-doe")
    delete = index_of(cur, "DELETE FROM survey_ratings")
    move = index_of(cur, "UPDATE survey_ratings")
    assert delete < move
    sql = cur.calls[delete][0]
    assert "IS NOT DISTINCT FROM" in sql and "d.updated_at" in sql
    assert "status = 'merged'" in cur.calls[index_of(cur, "UPDATE survey_pending_professors")][0]


def test_merge_into_an_unknown_slug_raises():
    cur = FakeCursor({"FROM survey_pending_professors": [PENDING]})
    with pytest.raises(rr.ReviewError):
        rr.merge_professor(cur, "p1", "nobody")
    assert not cur.statements("DELETE") and not cur.statements("UPDATE")


def test_reject_professor_deletes_only_its_ratings():
    cur = FakeCursor({"FROM survey_pending_professors": [PENDING]})
    rr.reject_professor(cur, "p1")
    (sql, params), = cur.statements("DELETE")
    assert sql.split("WHERE")[1].strip() == "pending_professor_id = %s"
    assert params == ("p1",)
    assert "status = 'rejected'" in cur.statements("UPDATE")[0][0]


def test_approve_course_moves_ratings_onto_the_pending_code():
    course = {"id": "c1", "code": "CS9999", "name": "Topics", "status": "pending"}
    cur = FakeCursor({"FROM survey_pending_courses": [course]})
    rr.approve_course(cur, "c1")
    assert index_of(cur, "DELETE FROM survey_ratings") < index_of(cur, "UPDATE survey_ratings")
    (sql, params), _ = cur.statements("UPDATE survey_ratings")
    assert "course_code = %s" in sql and "pending_course_id = NULL" in sql
    assert params == ("CS9999", "c1")


def test_moved_ratings_on_an_untaught_pair_are_held():
    # A merge is a judgment about the person, not about who taught the course, and the form
    # skipped the pair check while the entry was pending.
    cur = FakeCursor({"FROM survey_pending_professors": [PENDING],
                      "SELECT 1 FROM professors": [{"?column?": 1}],
                      "RETURNING id::text": [{"id": "r1"}, {"id": "r2"}]})
    summary = rr.merge_professor(cur, "p1", "jane-doe")
    _, (sql, params) = cur.statements("UPDATE survey_ratings")
    assert "status = 'held'" in sql and "concat_ws(',', r.hold_reasons, 'unverified_pair')" in sql
    assert "AND NOT (EXISTS (SELECT 1 FROM banner_course_instructors" in sql
    assert "course_code = r.course_code AND professor_slug = r.professor_slug" in sql
    assert params == (["r1", "r2"],)
    assert "moved 2 rating(s)" in summary


def test_merge_course_accepts_a_banner_only_code():
    course = {"id": "c1", "code": "CS1880", "name": "Discrete", "status": "pending"}
    cur = FakeCursor({"FOR UPDATE": [course], "banner_course_offerings": [{"x": 1}]})
    rr.merge_course(cur, "c1", "CS1800")
    assert cur.statements("UPDATE survey_ratings")[0][1] == ("CS1800", "c1")
    cur = FakeCursor({"FOR UPDATE": [course]})
    with pytest.raises(rr.ReviewError):
        rr.merge_course(cur, "c1", "ZZ0000")
    assert not cur.statements("DELETE") and not cur.statements("UPDATE")


def test_list_matches_last_names_on_the_folded_key_and_escapes_wildcards():
    def like_param(name_key):
        cur = FakeCursor({"FROM survey_pending_professors": [
            {"id": "p1", "name": "Ana Muñoz", "name_key": name_key, "department": None, "n": 1}]})
        rr.list_pending(cur)
        return next(p for s, p in cur.calls if "name_key LIKE" in s)[0]
    assert like_param("ana munoz") == "% munoz"
    assert like_param("ana mu%n_z") == "% mu\%n\_z"


def test_approve_rating_only_touches_held_rows():
    cur = FakeCursor({"UPDATE survey_ratings": [{"id": "abcd1234"}]})
    rr.approve_rating(cur, "abcd1234")
    (sql, params), = cur.calls
    assert "status = 'held'" in sql and "'accepted'" in sql
    assert "updated_at" not in sql
    assert params == ("abcd1234%",)
    with pytest.raises(rr.ReviewError):
        rr.approve_rating(FakeCursor(), "abcd1234")


def test_list_prints_no_hashes(capsys):
    held = {"id": "abcd1234-0000", "professor": "jane-doe", "course": "CS2500",
            "term_label": "Fall 2025", "rating": 2, "difficulty": 5, "hold_reasons": "burst",
            "comment": "x" * 100, "created_at": "2026-10-01",
            "device_hash": "DEVICEHASH", "ip_hash": "IPHASH"}
    cur = FakeCursor({"FROM survey_ratings": [held]})
    rr.list_pending(cur)
    out = capsys.readouterr().out
    assert "abcd1234" in out and "jane-doe" in out and "x" * 80 in out and "x" * 81 not in out
    assert "difficulty 5/5" in out
    assert "DEVICEHASH" not in out and "IPHASH" not in out


def test_reject_rating_only_deletes_held_rows():
    cur = FakeCursor({"DELETE FROM survey_ratings": [{"id": "abcd1234"}]})
    rr.reject_rating(cur, "abcd1234")
    assert "status = 'held'" in cur.calls[0][0]
    with pytest.raises(rr.ReviewError):
        rr.reject_rating(FakeCursor(), "abcd1234")


def test_list_strips_control_characters(capsys):
    evil = "[2J"
    held = {"id": "abcd1234-0000", "professor": "jane-doe", "course": "CS2500",
            "term_label": None, "rating": 2, "difficulty": None, "hold_reasons": "burst",
            "comment": "hi" + evil, "created_at": "2026-10-01"}
    cur = FakeCursor({"FROM survey_ratings": [held],
                      "FROM survey_pending_professors": [{"id": "p1", "name": "Eve" + evil,
                                                          "name_key": "eve x", "department": evil,
                                                          "n": 1}],
                      "FROM survey_pending_courses": [{"id": "c1", "code": evil, "name": evil,
                                                       "n": 1, "in_catalog": False}]})
    rr.list_pending(cur)
    assert "" not in capsys.readouterr().out


SECRET = "s" * 32


class FakeConn:
    def __init__(self, cur):
        self.cur, self.commits = cur, 0

    def cursor(self, cursor_factory=None):
        cur = self.cur

        class Ctx:
            def __enter__(self):
                return cur

            def __exit__(self, *a):
                return False
        return Ctx()

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.mark.parametrize("argv", [["approve-rating", "beef5678"], ["reject-rating", "beef5678"],
                                  ["remove-comment", "abcdef123456"], ["approve-professor", "beef5678"]])
def test_commands_that_change_pages_bump_data_version(argv, monkeypatch):
    cur = FakeCursor()
    monkeypatch.setattr(rr, "run", lambda c, args: "ok")
    monkeypatch.setattr(rr, "connect", lambda: FakeConn(cur))
    assert rr.main(argv) == 0
    assert any("'data_version'" in sql for sql, _ in cur.calls)


@pytest.mark.parametrize("argv", [["list"], ["purge-ip"]])
def test_read_only_commands_do_not_bump_data_version(argv, monkeypatch):
    cur = FakeCursor()
    monkeypatch.setattr(rr, "run", lambda c, args: "ok")
    monkeypatch.setattr(rr, "connect", lambda: FakeConn(cur))
    assert rr.main(argv) == 0
    assert not any("'data_version'" in sql for sql, _ in cur.calls)


def test_remove_comment_finds_the_review_by_its_public_id(monkeypatch):
    import survey_reviews
    monkeypatch.setenv("RATING_SECRET", SECRET)
    target, other = "11111111-0000-0000-0000-000000000000", "22222222-0000-0000-0000-000000000000"
    cur = FakeCursor({"SELECT id FROM survey_ratings": [{"id": other}, {"id": target}],
                      "UPDATE survey_ratings": [{"id": target}]})
    rr.remove_comment(cur, survey_reviews.public_id(SECRET, target))
    (sql, params), = cur.statements("UPDATE")
    assert "comment = NULL" in sql and "comment_hash" not in sql and params == (target,)
    assert "'comment_removed'" in sql   # marks the row, so an edit bringing the comment back is held


def test_remove_comment_with_an_unknown_id_raises(monkeypatch):
    monkeypatch.setenv("RATING_SECRET", SECRET)
    cur = FakeCursor({"SELECT id FROM survey_ratings": [{"id": "11111111-0000-0000-0000-000000000000"}]})
    with pytest.raises(rr.ReviewError):
        rr.remove_comment(cur, "abcdef123456")


def test_remove_comment_needs_the_rating_secret(monkeypatch):
    monkeypatch.delenv("RATING_SECRET", raising=False)
    with pytest.raises(rr.ReviewError):
        rr.remove_comment(FakeCursor(), "abcdef123456")


def _abuse_cursor(network):
    return FakeCursor({"SELECT device_hash": [{"device_hash": "d", "ip_hash": "i", "network_type": network}],
                       "DELETE FROM survey_ratings": [{"id": "abcd1234"}]})


def test_abuse_reject_flags_device_and_ip_then_deletes():
    cur = _abuse_cursor("other")
    rr.reject_rating(cur, "abcd1234", abuse=True)
    device, ip = cur.statements("INSERT INTO rating_flags")
    assert "ON CONFLICT" in device[0] and "DO NOTHING" in device[0] and device[1] == ("device", "d")
    assert "DO UPDATE SET created_at = now()" in ip[0] and ip[1] == ("ip", "i")
    delete = index_of(cur, "DELETE FROM survey_ratings")
    assert cur.calls.index(device) < delete and cur.calls.index(ip) < delete


def test_abuse_reject_on_campus_flags_only_the_device():
    cur = _abuse_cursor("campus")
    rr.reject_rating(cur, "abcd1234", abuse=True)
    assert [p for _, p in cur.statements("INSERT INTO rating_flags")] == [("device", "d")]


def test_abuse_reject_on_mobile_flags_only_the_device():
    cur = _abuse_cursor("mobile")
    rr.reject_rating(cur, "abcd1234", abuse=True)
    assert [p for _, p in cur.statements("INSERT INTO rating_flags")] == [("device", "d")]


def test_abuse_reject_with_a_purged_ip_flags_only_the_device():
    cur = FakeCursor({"SELECT device_hash": [{"device_hash": "d", "ip_hash": None, "network_type": "other"}],
                      "DELETE FROM survey_ratings": [{"id": "abcd1234"}]})
    rr.reject_rating(cur, "abcd1234", abuse=True)
    assert [p for _, p in cur.statements("INSERT INTO rating_flags")] == [("device", "d")]


def test_abuse_reject_of_a_missing_id_flags_nothing():
    cur = FakeCursor()
    with pytest.raises(rr.ReviewError):
        rr.reject_rating(cur, "abcd1234", abuse=True)
    assert not cur.statements("INSERT INTO rating_flags") and not cur.statements("DELETE")


def test_reject_without_abuse_flags_nothing():
    cur = _abuse_cursor("other")
    rr.reject_rating(cur, "abcd1234")
    assert not cur.statements("INSERT INTO rating_flags")


def test_parse_reject_rating_abuse_flag():
    assert rr.parse_args(["reject-rating", "--abuse", "ab12cd34"]).abuse is True
    assert rr.parse_args(["reject-rating", "ab12cd34"]).abuse is False
