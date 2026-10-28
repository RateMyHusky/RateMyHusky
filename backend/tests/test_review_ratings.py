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
    cur = FakeCursor({"comment_status = 'pending'": [], "FROM survey_ratings": [held]})
    rr.list_pending(cur)
    out = capsys.readouterr().out
    assert "abcd1234" in out and "jane-doe" in out and "x" * 80 in out and "x" * 81 not in out
    assert "difficulty 5/5" in out
    assert "DEVICEHASH" not in out and "IPHASH" not in out


def test_list_prints_each_waiting_comment_in_full(capsys):
    waiting = {"id": "beef5678-0000", "professor": "jane-doe", "course": "CS2500", "status": "accepted",
               "rating": 4, "comment": "y" * 300, "updated_at": "2026-10-01",
               "comment_check": "unchecked", "comment_check_reason": None}
    cur = FakeCursor({"comment_status = 'pending'": [waiting]})
    summary = rr.list_pending(cur)
    out = capsys.readouterr().out
    assert "Comments to review (1):" in out and "beef5678" in out and "y" * 300 in out
    assert "rating accepted" in out and "1 comments to review" in summary
    assert "not yet checked" in out


def test_list_shows_each_comments_check_and_puts_flagged_first(capsys):
    rows = [{"id": f"beef567{i}-0000", "professor": "jane-doe", "course": "CS2500", "status": "accepted",
             "rating": 4, "comment": "fine", "updated_at": "2026-10-01",
             "comment_check": check, "comment_check_reason": reason}
            for i, (check, reason) in enumerate((("review", "blocked"), ("allow", None),
                                                 ("unchecked", "duplicate")))]
    cur = FakeCursor({"comment_status = 'pending'": rows})
    rr.list_pending(cur)
    out = capsys.readouterr().out
    assert "flagged: blocked" in out and "  clean  " in out and "not yet checked (duplicate)" in out
    sql = next(s for s, _ in cur.calls if "comment_status = 'pending'" in s)
    assert "ORDER BY r.comment_check IS DISTINCT FROM 'review', r.updated_at" in sql


def test_approve_comment_only_touches_waiting_comments():
    cur = FakeCursor({"UPDATE survey_ratings": [{"id": "abcd1234"}]})
    rr.approve_comment(cur, "abcd1234")
    (sql, params), = cur.calls
    assert "comment_status = 'approved'" in sql and "comment_status = 'pending'" in sql
    assert "status = 'held'" not in sql and "updated_at" not in sql
    # Off the moderation queue, so a run racing the approval can't hold the rating.
    assert "comment_next_check_at = NULL" in sql
    assert params == ("abcd1234%",)
    with pytest.raises(rr.ReviewError):
        rr.approve_comment(FakeCursor(), "abcd1234")


def test_reject_comment_drops_the_text_and_keeps_the_rating():
    cur = FakeCursor({"UPDATE survey_ratings": [{"id": "abcd1234"}]})
    rr.reject_comment(cur, "abcd1234")
    (sql, params), = cur.calls
    assert sql.startswith("UPDATE") and "comment = NULL" in sql and "comment_status = NULL" in sql
    assert "'comment_removed'" in sql and "comment_hash" not in sql
    assert "comment_check = NULL" in sql and "comment_next_check_at = NULL" in sql
    assert "WHERE id::text LIKE %s AND comment_status = 'pending'" in sql and params == ("abcd1234%",)
    with pytest.raises(rr.ReviewError):
        rr.reject_comment(FakeCursor(), "abcd1234")


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
    waiting = {"id": "beef5678-0000", "professor": "jane-doe", "course": "CS2500", "status": "accepted",
               "rating": 2, "comment": "yo" + evil, "updated_at": "2026-10-01",
               "comment_check": "review", "comment_check_reason": "x" + evil}
    cur = FakeCursor({"comment_status = 'pending'": [waiting], "FROM survey_ratings": [held],
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
                                  ["remove-comment", "abcdef123456"], ["approve-professor", "beef5678"],
                                  ["approve-comment", "beef5678"], ["reject-comment", "beef5678"]])
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
    assert "comment_status = NULL" in sql
    assert "'comment_removed'" in sql   # marks the row, so an edit bringing the comment back is held
    # Only a shown comment has a public id to report.
    assert "comment_status = 'approved'" in cur.calls[0][0]


def test_remove_comment_with_an_unknown_id_raises(monkeypatch):
    monkeypatch.setenv("RATING_SECRET", SECRET)
    cur = FakeCursor({"SELECT id FROM survey_ratings": [{"id": "11111111-0000-0000-0000-000000000000"}]})
    with pytest.raises(rr.ReviewError):
        rr.remove_comment(cur, "abcdef123456")


def test_remove_comment_needs_the_rating_secret(monkeypatch):
    monkeypatch.delenv("RATING_SECRET", raising=False)
    with pytest.raises(rr.ReviewError):
        rr.remove_comment(FakeCursor(), "abcdef123456")
