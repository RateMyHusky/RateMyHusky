from datetime import datetime, timedelta, timezone

import pytest

from pipeline import run

URL = "https://www.ratemyprofessors.com/professor/"
TABLES = {
    "rmp_professors": [
        {"name": "Olin Guha", "department": "CS", "rating": 4.0, "num_ratings": 1,
         "would_take_again_pct": "90%", "level_of_difficulty": 3.0, "professor_url": URL + "1"},
        {"name": "Ada Lovelace", "department": "Math", "rating": 5.0, "num_ratings": 1,
         "would_take_again_pct": "100%", "level_of_difficulty": 2.0, "professor_url": URL + "2"},
    ],
    "rmp_links": [{"rmp_id": 1, "rmp_name": "Olin Guha", "rmp_department": "CS",
                   "professor_url": URL + "1", "slug": "olin-guha", "match_method": "frozen"}],
    "professors": [{"slug": "olin-guha", "name": "Olin Guha", "name_key": "olin guha",
                    "department": "CS", "college": "Khoury", "image_url": None,
                    "focus_x": None, "focus_y": None}],
    "catalog_courses": [{"code": "CS2500", "name": "Fundamentals", "department": "CS",
                         "subject": "CS", "search_text": "cs2500", "is_placeholder": False}],
    "rmp_reviews": [{"id": 10, "professor_name": "Olin Guha", "department": "CS", "name_key": None,
                     "course": "cs2500", "quality": 4.0, "difficulty": 3.0, "grade": "A",
                     "comment": "good", "visible": True}],
    "banner_course_instructors": [
        {"subject_course": "CS3100", "instructor_key": "lucia nunez", "instructor_name": "Nunez, Lucia",
         "professor_slug": None, "match_method": "no_match", "terms_taught": 2, "sections": 2, "last_term_code": "202630"},
        {"subject_course": "CS2500", "instructor_key": "olin guha", "instructor_name": "Guha, Olin",
         "professor_slug": "olin-guha", "match_method": "name_key", "terms_taught": 3,
         "sections": 3, "last_term_code": "202630"},
    ],
    # TRACK_SECTIONS_SQL opens with a CTE, so _rows matches it by object.
    "track_sections": [
        {"instructor_key": None, "professor_slug": None, "track": None, "sections": None, "cps_subject": "PJM",
         "cps_share": 0.9},
        {"instructor_key": None, "professor_slug": None, "track": None, "sections": None, "cps_subject": "ITC",
         "cps_share": 0.58},
        {"instructor_key": "olin guha", "professor_slug": "olin-guha", "track": "Law Semester", "sections": 3,
         "cps_subject": None, "cps_share": None},
        {"instructor_key": "lucia nunez", "professor_slug": None, "track": "CPS Quarter", "sections": 1,
         "cps_subject": None, "cps_share": None},
    ],
    "survey_ratings": [{"id": "r1", "professor_slug": "olin-guha", "course_code": "CS2500", "rating": 5,
                        "difficulty": 2, "hours": "3-4", "grade": None, "comment": "", "hold_reasons": None,
                        "updated_at": datetime.now(timezone.utc) - timedelta(days=1)}],
    "survey_pending_courses": [],
    "banner_course_offerings": [],
    "stats_cache": [],
}


def _rows(sql):
    by_sql = {run.banner_roster.TRACK_SECTIONS_SQL: "track_sections"}
    return [dict(r) for r in TABLES[by_sql.get(sql) or sql.split(" FROM ")[1].split()[0]]]


@pytest.fixture
def captured(monkeypatch):
    sqls, written = [], {}

    def fetch(conn, sql):
        sqls.append(sql)
        return _rows(sql)

    monkeypatch.setattr(run, "connect", lambda: object())
    monkeypatch.setattr(run, "fetch_all", fetch)
    monkeypatch.setattr(run.roster, "apply_roster", lambda *a: None)
    monkeypatch.setattr(run.banner_roster, "apply_banner_professors", lambda *a: None)
    monkeypatch.setattr(run.course_codes, "apply_codes", lambda *a: 0)
    monkeypatch.setattr(run.name_keys, "apply_name_keys", lambda *a: 0)
    monkeypatch.setattr(run.review_tags, "rebuild_if_present", lambda *a: None)
    monkeypatch.setattr(run.read_models, "verify", lambda *a: [])
    monkeypatch.setattr(run.read_models, "write",
                        lambda conn, catalog, courses, summary_rows, counts: written.update(
                            summary_rows=summary_rows))
    # Only once the read models are written: a failed run must leave its window to the next one.
    monkeypatch.setattr(run.survey, "mark_surge_checked",
                        lambda conn, now: written.update(checked=now) if "summary_rows" in written else None)
    return sqls, written


@pytest.fixture
def writes(monkeypatch):
    calls = []
    monkeypatch.setattr(run, "connect", lambda: object())
    monkeypatch.setattr(run, "fetch_all", lambda conn, sql: _rows(sql))
    monkeypatch.setattr(run.roster, "apply_roster", lambda conn, l, p: calls.append(("roster", l, p)))
    monkeypatch.setattr(run.banner_roster, "apply_banner_professors",
                        lambda conn, rows: calls.append(("banner", rows)))
    monkeypatch.setattr(run.course_codes, "apply_codes", lambda conn, p: calls.append(("codes", p)) or 0)
    monkeypatch.setattr(run.name_keys, "apply_name_keys", lambda conn, p: calls.append(("name_keys", p)) or 0)
    monkeypatch.setattr(run.review_tags, "rebuild_if_present", lambda conn: calls.append(("tags",)))
    monkeypatch.setattr(run.read_models, "write", lambda conn, *a: calls.append(("read_models", a[0])))
    monkeypatch.setattr(run.survey, "mark_surge_checked", lambda conn, now: None)
    return calls


def test_a_failed_verify_writes_nothing(writes):
    assert run.main([]) == 1                      # 2 professors, far under MIN_PROFESSORS
    assert writes == []


def test_a_dry_run_writes_nothing(writes, monkeypatch):
    monkeypatch.setattr(run.read_models, "verify", lambda *a: [])
    assert run.main(["--dry-run"]) == 0
    assert writes == []


def test_writes_happen_after_verify_in_order(writes, monkeypatch):
    monkeypatch.setattr(run.read_models, "verify", lambda *a: [])
    assert run.main([]) == 0
    assert [c[0] for c in writes] == ["roster", "banner", "codes", "name_keys", "tags", "read_models"]
    _, new_links, new_professors = writes[0]
    assert [l["rmp_id"] for l in new_links] == [2] and [p["name"] for p in new_professors] == ["Ada Lovelace"]
    assert [p["slug"] for p in writes[1][1]] == ["lucia-nunez"]
    assert writes[1][1][0]["department"] == "CS"
    assert writes[2][1] == [(10, "CS2500")]
    assert writes[3][1] == [(10, "olin guha")]


def test_term_track_sets_catalog_college_for_linked_and_new_banner_professors(writes, monkeypatch):
    monkeypatch.setattr(run.read_models, "verify", lambda *a: [])
    assert run.main([]) == 0
    catalog = {r["slug"]: r["college"] for r in writes[-1][1]}
    assert catalog["olin-guha"] == "Law"                       # linked by the matcher
    assert catalog["lucia-nunez"] == "Professional Studies"    # created this run, linked by name_key


def _caep(monkeypatch, track):
    monkeypatch.setattr(run.read_models, "verify", lambda *a: [])
    olin = TABLES["professors"][0]
    monkeypatch.setitem(TABLES, "professors", [
        {**olin, "department": "Counseling & Educational Psych", "college": "Professional Studies"}])
    monkeypatch.setitem(TABLES, "track_sections", [
        {"instructor_key": "olin guha", "professor_slug": "olin-guha", "track": track, "sections": 3,
         "cps_subject": None, "cps_share": None}])


def test_a_corrected_department_label_is_shown(writes, monkeypatch):
    _caep(monkeypatch, "Semester")
    assert run.main([]) == 0
    assert {r["slug"]: r["college"] for r in writes[-1][1]}["olin-guha"] == "Health Sciences"


def test_the_subject_vote_and_the_law_exits_read_the_corrected_label(writes, monkeypatch):
    # They skip professors by college, so the correction has to come first.
    _caep(monkeypatch, "Semester")
    seen = {}
    real_subjects, real_exits = run.banner_roster.subject_colleges, run.banner_roster.track_exits

    def subjects(rows, profs, *a):
        seen["subject_colleges"] = {p["slug"]: p["college"] for p in profs}
        return real_subjects(rows, profs, *a)

    def exits(track_rows, new, profs, *a):
        seen["track_exits"] = {p["slug"]: p["college"] for p in profs}
        return real_exits(track_rows, new, profs, *a)

    monkeypatch.setattr(run.banner_roster, "subject_colleges", subjects)
    monkeypatch.setattr(run.banner_roster, "track_exits", exits)
    assert run.main([]) == 0
    assert seen["subject_colleges"]["olin-guha"] == "Health Sciences"
    assert seen["track_exits"]["olin-guha"] == "Health Sciences"


def test_the_term_track_wins_over_a_corrected_department_label(writes, monkeypatch):
    _caep(monkeypatch, "CPS Quarter")
    assert run.main([]) == 0
    assert {r["slug"]: r["college"] for r in writes[-1][1]}["olin-guha"] == "Professional Studies"


def test_the_log_names_voted_subjects_near_the_bar(captured, capsys):
    run.main(["--dry-run"])
    assert "CPS Quarter subjects by vote: 2 (near the bar: ITC 58%); " in capsys.readouterr().out


def test_survey_rows_reach_the_read_models(captured):
    _, written = captured
    assert run.main([]) == 0
    by = {(r["professor_slug"], r["course_code"], r["source"]): r for r in written["summary_rows"]}
    assert ("olin-guha", "", "survey") in by
    assert by[("olin-guha", "", "blend")]["num_ratings"] == 2      # 1 RMP + 1 survey


def test_a_weekly_surge_is_left_out_and_held_only_after_verify(captured, monkeypatch, capsys):
    _, written = captured
    surge = [dict(TABLES["survey_ratings"][0], id=f"s{i}", rating=1)
             for i in range(run.survey.WEEKLY_SURGE_PROF + 1)]
    monkeypatch.setitem(TABLES, "survey_ratings", surge)
    held = []
    monkeypatch.setattr(run.survey, "apply_surge_holds", lambda conn, ids: held.append(ids) or len(ids))
    assert run.main(["--dry-run"]) == 0
    assert held == [] and "::warning::41 survey ratings" in capsys.readouterr().out
    assert run.main([]) == 0
    assert held == [{r["id"] for r in surge}]
    sources = {r["source"] for r in written["summary_rows"] if r["professor_slug"] == "olin-guha"}
    assert "survey" not in sources


def test_only_accepted_ratings_with_a_professor_are_read(captured):
    sqls, _ = captured
    run.main(["--dry-run"])
    [sql] = [s for s in sqls if "FROM survey_ratings" in s]
    assert "status = 'accepted' AND professor_slug IS NOT NULL" in sql
    # Only approved comments count toward num_comments.
    assert "CASE WHEN comment_status = 'approved' THEN comment END" in sql


def test_the_surge_scan_reaches_back_to_the_last_run_that_published(captured, monkeypatch):
    # The weekly run failed last Sunday: a surge 10 days back must still be held.
    _, written = captured
    old = datetime.now(timezone.utc) - timedelta(days=10)
    surge = [dict(TABLES["survey_ratings"][0], id=f"s{i}", updated_at=old)
             for i in range(run.survey.WEEKLY_SURGE_PROF + 1)]
    monkeypatch.setitem(TABLES, "survey_ratings", surge)
    held = []
    monkeypatch.setattr(run.survey, "apply_surge_holds", lambda conn, ids: held.append(ids) or len(ids))
    assert run.main([]) == 0 and held == [set()]
    checked = int((datetime.now(timezone.utc) - timedelta(days=14)).timestamp())
    monkeypatch.setitem(TABLES, "stats_cache", [{"value": checked}])
    assert run.main([]) == 0 and held[-1] == {r["id"] for r in surge}
    assert written["checked"] > datetime.now(timezone.utc) - timedelta(minutes=1)


def test_a_retired_course_keeps_its_reviews_and_gets_a_row(captured, monkeypatch):
    # The catalog edition lists only the successor; Banner still titles the old code.
    monkeypatch.setitem(TABLES, "catalog_courses", [{"code": "CS2000", "name": "Program Design", "department": "CS",
                                                     "subject": "CS", "search_text": "cs2000", "is_placeholder": False}])
    monkeypatch.setitem(TABLES, "banner_course_offerings", [{"subject_course": "CS2500",
                                                             "course_title": "Fundamentals of Computer Science 1"}])
    out = {}
    monkeypatch.setattr(run.read_models, "write", lambda conn, catalog, courses, summary_rows, counts: out.update(
        codes=[c["code"] for c in courses], summaries={r["course_code"] for r in summary_rows}))
    assert run.main([]) == 0
    assert "CS2500" in out["codes"] and "CS2500" in out["summaries"]
