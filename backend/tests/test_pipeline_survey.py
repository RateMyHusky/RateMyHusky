from pipeline import survey

R = lambda slug, code, rating, hours, grade=None, comment="", difficulty=None: {
    "professor_slug": slug, "course_code": code, "rating": rating, "hours": hours,
    "grade": grade, "comment": comment, "difficulty": difficulty}

def test_rows_for_professor_course_and_pair():
    rows = survey.survey_rows([R("jane-doe", "CS2500", 5, "3-4", "A", "great"),
                               R("jane-doe", "CS2500", 3, "10+", None, "")])
    by = {(r["professor_slug"], r["course_code"]): r for r in rows}
    assert set(by) == {("jane-doe", ""), ("", "CS2500"), ("jane-doe", "CS2500")}
    p = by[("jane-doe", "")]
    assert (p["source"], p["rating"], p["num_ratings"], p["num_comments"]) == ("survey", 4.0, 2, 1)
    assert p["hours_per_week"] == round((3.5 + 12.0) / 2, 2)
    assert p["rating_distribution"] == {"1": 0, "2": 0, "3": 1, "4": 0, "5": 1}
    assert by[("jane-doe", "CS2500")]["grade_distribution"] == {"A": 1}
    assert p["difficulty"] is None and p["would_take_again_pct"] is None

def test_rating_on_a_pending_course_counts_nowhere_until_approved():
    # rating_key leaves course_code NULL while the course is pending, and invented
    # codes would otherwise move the professor's rating with no burst check per code.
    rows = survey.survey_rows([R("jane-doe", "CS2500", 5, "3-4"), R("jane-doe", None, 1, "0-2")])
    by = {(r["professor_slug"], r["course_code"]): r for r in rows}
    assert (by[("jane-doe", "")]["rating"], by[("jane-doe", "")]["num_ratings"]) == (5.0, 1)
    assert survey.survey_rows([R("jane-doe", None, 1, "0-2")]) == []

def test_difficulty_is_the_mean_of_ratings_that_answered_it():
    # Ratings from before the question was asked have no difficulty and don't count toward it.
    rows = survey.survey_rows([R("jane-doe", "CS2500", 5, "3-4", difficulty=4),
                               R("jane-doe", "CS2500", 3, "10+", difficulty=1),
                               R("jane-doe", "CS2500", 4, "0-2")])
    by = {(r["professor_slug"], r["course_code"]): r for r in rows}
    assert by[("jane-doe", "CS2500")]["difficulty"] == 2.5
    assert by[("jane-doe", "")]["difficulty"] == 2.5
    assert by[("jane-doe", "CS2500")]["num_difficulty"] == 2 and by[("jane-doe", "CS2500")]["num_ratings"] == 3

def test_no_ratings_no_rows():
    assert survey.survey_rows([]) == []

def test_approved_course_already_in_catalog_is_not_added_twice():
    cat = [{"code": "CS4973", "name": "Special Topics", "department": "CS", "subject": "CS",
            "search_text": "cs4973", "is_placeholder": False}]
    assert survey.approved_courses([{"code": "CS4973", "name": "Topics"}], cat) == []
    added = survey.approved_courses([{"code": "CS4974", "name": "Robots"}], cat)
    assert [(c["code"], c["subject"], c["is_placeholder"]) for c in added] == [("CS4974", "CS", False)]
    assert added[0]["search_text"] == "cs4974 robots" and added[0]["department"] is None


def test_two_approvals_of_the_same_code_add_one_course():
    added = survey.approved_courses([{"code": "CS4974", "name": "A"}, {"code": "CS4974", "name": "B"}], [])
    assert [c["code"] for c in added] == ["CS4974"]


from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)


def S(i, slug="jane-doe", code="CS2500", days_ago=1, hold_reasons=None):
    return {"id": f"r{i}", "professor_slug": slug, "course_code": code,
            "updated_at": NOW - timedelta(days=days_ago), "hold_reasons": hold_reasons}


def test_a_professors_week_over_the_limit_is_a_surge():
    # Under the daily cap a drip still lands ~200 a week; the pipeline is the last check before publish.
    week = [S(i, code=("CS2500", "CS3500")[i % 2]) for i in range(survey.WEEKLY_SURGE_PROF + 1)]
    assert survey.surge_ids(week, NOW) == {r["id"] for r in week}
    assert survey.surge_ids(week[:-1], NOW) == set()


def test_a_courses_week_spread_over_professors_is_a_surge():
    week = [S(i, slug=f"prof-{i % 10}") for i in range(survey.WEEKLY_SURGE_COURSE + 1)]
    assert survey.surge_ids(week, NOW) == {r["id"] for r in week}
    assert survey.surge_ids(week[:-1], NOW) == set()


def test_surge_counts_only_this_weeks_unreviewed_known_course_ratings():
    week = [S(i) for i in range(survey.WEEKLY_SURGE_PROF)]
    older = [S(100 + i, days_ago=8) for i in range(5)]
    approved = [S(200 + i, hold_reasons="weekly_surge") for i in range(5)]  # a reviewer cleared these
    pending = [S(300 + i, code=None) for i in range(5)]  # counts nowhere until approved
    assert survey.surge_ids(week + older + approved + pending, NOW) == set()
    extra = S(999)
    assert survey.surge_ids(week + older + approved + pending + [extra], NOW) == {r["id"] for r in week + [extra]}


def test_a_missed_weekly_run_still_checks_the_week_it_skipped():
    # The last run that published was 14 days ago; a surge 8-13 days back was never checked.
    missed = [S(i, days_ago=10) for i in range(survey.WEEKLY_SURGE_PROF + 1)]
    assert survey.surge_ids(missed, NOW) == set()
    assert survey.surge_ids(missed, NOW, since=NOW - timedelta(days=14)) == {r["id"] for r in missed}
    # A run more recent than a week ago still scans the whole week.
    assert survey.surge_ids([S(i) for i in range(41)], NOW, since=NOW - timedelta(hours=6)) != set()


def test_a_longer_scan_still_holds_only_a_week_over_the_limit():
    # 35 a week for two weeks is under the weekly limit in every 7 days.
    steady = [S(i, days_ago=(i % 14) + 0.5) for i in range(70)]
    assert survey.surge_ids(steady, NOW, since=NOW - timedelta(days=14)) == set()
    spike = [S(100 + i, days_ago=11) for i in range(survey.WEEKLY_SURGE_PROF + 1)]
    held = survey.surge_ids(spike + [S(200, days_ago=2)], NOW, since=NOW - timedelta(days=14))
    assert held == {r["id"] for r in spike}   # the rating a week after the spike isn't in its 7 days
