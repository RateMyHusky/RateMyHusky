"""The professor page payload (/api/professors/<slug>/full, spec §4.2).

A fake query records every statement, so the round-trip budget and the tables
touched are pinned alongside the contract's exact key sets.
"""

import uuid
from datetime import datetime, timezone

import psycopg2.errors

from professor_full import build_payload

CATALOG = {"slug": "olin-guha", "name": "Olin Guha", "name_key": "olin guha",
           "department": "Khoury", "college": "Khoury", "avg_rating": 4.2,
           "rmp_rating": 4.2, "num_ratings": 57, "total_reviews": 57,
           "would_take_again_pct": 88.0, "difficulty": 3.1,
           "professor_url": "https://www.ratemyprofessors.com/professor/1",
           "image_url": None, "focus_x": None, "focus_y": None, "total_comments": 3}

REVIEWS = [
    {"course": "CS3500", "course_code": "CS3500", "quality": 5, "difficulty": 3, "date": "2024", "tags": "",
     "attendance": "", "grade": "A", "textbook": "", "online_class": "", "comment": "Great."},
    {"course": "cs 3500", "course_code": "CS3500", "quality": 3, "difficulty": 4, "date": "2023", "tags": "",
     "attendance": "", "grade": "B", "textbook": "", "online_class": "", "comment": ""},
    {"course": "CS2500 ", "course_code": "CS2500", "quality": 4, "difficulty": 2, "date": "2022", "tags": "",
     "attendance": "", "grade": "", "textbook": "", "online_class": "", "comment": "Fine."},
    {"course": "FUNDIES", "course_code": None, "quality": 2, "difficulty": 5, "date": "2021", "tags": "",
     "attendance": "", "grade": "", "textbook": "", "online_class": "", "comment": "Hard."},
]

MENTIONS = [{"body": "guha is great", "sentiment": "positive", "sentiment_score": 0.6,
             "score": 12, "subreddit": "NEU", "permalink": "/r/x", "created_utc": None}]


SUMMARY_ROWS = [
    {"professor_slug": "olin-guha", "course_code": "", "source": "rmp", "rating": 4.2, "difficulty": 3.1, "would_take_again_pct": 88.0,
     "num_ratings": 57, "num_comments": 3, "hours_per_week": None,
     "rating_distribution": {"1": 1, "2": 2, "3": 4, "4": 20, "5": 30}, "grade_distribution": {"A": 9},
     "course_name": None},
    {"professor_slug": "olin-guha", "course_code": "", "source": "blend", "rating": 4.2, "difficulty": 3.1, "would_take_again_pct": 88.0,
     "num_ratings": 57, "num_comments": 3, "hours_per_week": None,
     "rating_distribution": {"1": 1, "2": 2, "3": 4, "4": 20, "5": 30}, "grade_distribution": {"A": 9},
     "course_name": None},
    {"professor_slug": "olin-guha", "course_code": "CS3500", "source": "blend", "rating": 4.0, "difficulty": 3.5, "would_take_again_pct": None,
     "num_ratings": 2, "num_comments": 1, "hours_per_week": None,
     "rating_distribution": {"3": 1, "5": 1}, "grade_distribution": {}, "course_name": "Object-Oriented Design"},
    {"professor_slug": "olin-guha", "course_code": "CS2500", "source": "blend", "rating": 4.0, "difficulty": 2.0, "would_take_again_pct": None,
     "num_ratings": 1, "num_comments": 1, "hours_per_week": None,
     "rating_distribution": {"4": 1}, "grade_distribution": {}, "course_name": None},
    {"professor_slug": "olin-guha", "course_code": "CS3500", "source": "rmp", "rating": 4.0, "difficulty": 3.5, "would_take_again_pct": None,
     "num_ratings": 2, "num_comments": 1, "hours_per_week": None,
     "rating_distribution": {"3": 1, "5": 1}, "grade_distribution": {}, "course_name": "Object-Oriented Design"},
]


def srow(**kw):
    """An accepted survey_ratings row as survey_reviews.fetch_rows returns it."""
    when = datetime(2026, 10, 20, tzinfo=timezone.utc)
    return {"id": uuid.uuid4(), "professor_slug": "olin-guha", "course_code": "CS3500",
            "course_name": "Object-Oriented Design", "term_label": "Fall 2025", "term_enrollment": 40,
            "terms_in_year": 1, "rating": 5, "difficulty": 3, "hours": "5-7", "grade": "A",
            "comment": "Loved it", "created_at": when, "updated_at": when, **kw}


class FakeDB:
    """`survey`: the survey_ratings rows, or an exception the read raises."""

    def __init__(self, catalog=CATALOG, reviews=REVIEWS, summaries=SUMMARY_ROWS, survey=()):
        self.catalog, self.reviews, self.summaries = catalog, reviews, summaries
        self.survey = survey
        self.calls = []

    def query(self, sql, params=None):
        self.calls.append((sql, params))
        s = " ".join(sql.split()).lower()
        if "from rmp_reviews" in s:
            return [dict(r) for r in self.reviews]
        if "from source_summary" in s:
            return [dict(r) for r in self.summaries]
        if "from survey_ratings" in s:
            if isinstance(self.survey, Exception):
                raise self.survey
            return [dict(r) for r in self.survey]
        if "from banner_course_instructors" in s:
            return []
        raise AssertionError(f"unexpected query: {sql}")

    def query_one(self, sql, params=None):
        self.calls.append((sql, params))
        s = " ".join(sql.split()).lower()
        if "from professors_catalog where slug" in s:
            return dict(self.catalog) if self.catalog and params[0] == self.catalog["slug"] else None
        if "from professors_catalog where name_key" in s:
            return dict(self.catalog) if self.catalog and params[0] == self.catalog["name_key"] else None
        raise AssertionError(f"unexpected query_one: {sql}")


AWARDS = {"olin guha": [{"award": "University Excellence in Teaching Award", "awardingBody": "Northeastern University",
                          "year": 2023, "yearLabel": "2022\u201323", "sourceUrl": "https://example.edu/awards"}]}


def _build(slug="olin-guha", db=None, mentions=MENTIONS, awards=AWARDS, history=None, review_id=None):
    """`history`: a fake course_history_for. None runs the real one against FakeDB,
    which has no Banner rows."""
    db = db or FakeDB()
    seen = {}

    def fetch_reddit_mentions(s, query_fn, mod_filter=""):
        # The Reddit round trip itself is counted by the route test.
        seen["slug"] = s
        return [dict(m) for m in mentions]

    extra = {} if history is None else {"course_history_for": history}
    if review_id is not None:
        extra["review_id"] = review_id
    data = build_payload(slug, db.query, db.query_one, lambda t: t, fetch_reddit_mentions,
                         awards_for=lambda key: [dict(a) for a in awards.get(key, [])], **extra)
    return data, db, seen


# ── contract key sets (spec §4.2) ──

def test_top_level_keys():
    data, _, _ = _build()
    assert set(data) == {"version", "identity", "summary", "sources", "courses", "redditMentions",
                         "awards", "lastTaught"}
    assert data["version"] == 2


def test_awards_join_on_the_catalog_name_key():
    data, _, _ = _build()
    assert data["awards"] == AWARDS["olin guha"]


def test_no_awards_is_an_empty_list():
    data, _, _ = _build(awards={})
    assert data["awards"] == []


def test_identity_keys():
    data, _, _ = _build()
    assert data["identity"] == {"slug": "olin-guha", "name": "Olin Guha", "department": "Khoury",
                                "college": "Khoury", "imageUrl": None, "focusX": 50.0, "focusY": 30.0}


def test_summary_keys_and_values():
    data, _, _ = _build()
    assert data["summary"] == {
        "rating": 4.2, "difficulty": 3.1, "wouldTakeAgainPct": 88.0, "numRatings": 57,
        "numComments": 4,   # 3 RMP comments + 1 Reddit mention
        "hoursPerWeek": None,
        "bySource": {"rmp": {"rating": 4.2, "numRatings": 57}},
    }


def test_sources_holds_rmp_and_survey_with_exact_keys():
    data, _, _ = _build()
    assert set(data["sources"]) == {"rmp", "survey"}
    assert set(data["sources"]["rmp"]) == {
        "available", "rating", "difficulty", "wouldTakeAgainPct", "numRatings",
        "professorUrl", "ratingDistribution", "gradeDistribution", "reviews"}


def test_survey_section_present_and_empty_without_ratings():
    data, _, _ = _build()
    assert data["sources"]["survey"] == {
        "available": False, "rating": None, "numRatings": 0, "hoursPerWeek": None,
        "ratingDistribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}, "gradeDistribution": {},
        "reviews": []}


def test_survey_section_from_the_survey_row():
    survey = {"course_code": "", "source": "survey", "rating": 4.0, "difficulty": None,
              "would_take_again_pct": None, "num_ratings": 3, "num_comments": 1, "hours_per_week": 8.5,
              "rating_distribution": {"3": 1, "4": 1, "5": 1}, "grade_distribution": {"A": 2}, "course_name": None}
    data, _, _ = _build(db=FakeDB(summaries=[*SUMMARY_ROWS, survey]))
    assert data["sources"]["survey"] == {
        "available": True, "rating": 4.0, "numRatings": 3, "hoursPerWeek": 8.5,
        "ratingDistribution": {"1": 0, "2": 0, "3": 1, "4": 1, "5": 1}, "gradeDistribution": {"A": 2},
        "reviews": []}


def test_course_row_keys():
    data, _, _ = _build()
    assert all(set(c) == {"code", "name", "rating", "difficulty", "numRatings", "ratingDistribution",
                          "terms", "lastTerm", "hasPage"} for c in data["courses"])


# ── courses[] ──

def test_courses_come_from_the_course_rows():
    data, _, _ = _build()
    by_code = {c["code"]: c for c in data["courses"]}
    assert [c["code"] for c in data["courses"]] == ["CS3500", "CS2500"]
    assert by_code["CS3500"]["numRatings"] == 2
    assert by_code["CS3500"]["rating"] == 4.0
    assert by_code["CS3500"]["name"] == "Object-Oriented Design"
    assert by_code["CS3500"]["ratingDistribution"] == {"1": 0, "2": 0, "3": 1, "4": 0, "5": 1}
    assert by_code["CS2500"]["name"] is None


def test_courses_ordered_by_rating_count_then_code():
    data, _, _ = _build()
    assert [c["code"] for c in data["courses"]] == ["CS3500", "CS2500"]


def test_reviews_carry_their_pipeline_course_code():
    data, _, _ = _build()
    assert [r["courseCode"] for r in data["sources"]["rmp"]["reviews"]] == ["CS3500", "CS3500", "CS2500", None]


def test_rmp_distributions_come_from_the_summary_row():
    data, _, _ = _build()
    assert data["sources"]["rmp"]["ratingDistribution"] == {"1": 1, "2": 2, "3": 4, "4": 20, "5": 30}
    assert data["sources"]["rmp"]["gradeDistribution"] == {"A": 9}


# ── Banner teaching history ──

HISTORY = [
    {"code": "CS3100", "name": "Program Design and Implementation 2", "termsTaught": 3,
     "lastTerm": "Fall 2026", "recentTerms": ["Fall 2026", "Spring 2026", "Fall 2025"],
     "avgClassSize": 111, "hasPage": False},
    {"code": "CS2500", "name": "Fundamentals of Computer Science 1", "termsTaught": 2,
     "lastTerm": "Fall 2024", "recentTerms": ["Fall 2024", "Fall 2023"],
     "avgClassSize": 80, "hasPage": False},
]


def _with_history(history=HISTORY, **kw):
    calls = []

    def course_history_for(slug, query):
        calls.append(slug)
        return [dict(h) for h in history]

    data, db, seen = _build(history=course_history_for, **kw)
    return data, calls


def test_taught_courses_come_first_in_history_order_then_most_rated():
    data, _ = _with_history()
    assert [c["code"] for c in data["courses"]] == ["CS3100", "CS2500", "CS3500"]


def test_banner_only_course_has_no_ratings():
    data, _ = _with_history()
    assert data["courses"][0] == {
        "code": "CS3100", "name": "Program Design and Implementation 2", "rating": None,
        "difficulty": None, "numRatings": 0, "ratingDistribution": None,
        "terms": ["Fall 2026", "Spring 2026", "Fall 2025"], "lastTerm": "Fall 2026", "hasPage": False}


def test_reviewed_course_with_history_keeps_its_ratings_and_gains_terms():
    data, _ = _with_history()
    cs2500 = data["courses"][1]
    assert (cs2500["rating"], cs2500["numRatings"]) == (4.0, 1)
    # No course_catalog row (course_name None): Banner's title fills in.
    assert cs2500["name"] == "Fundamentals of Computer Science 1"
    assert cs2500["terms"] == ["Fall 2024", "Fall 2023"]
    assert cs2500["lastTerm"] == "Fall 2024"


def test_two_history_rows_for_one_code_make_one_course_row_newest_wins():
    older = {**HISTORY[1], "code": "CS2500", "lastTerm": "Fall 2020", "recentTerms": ["Fall 2020"]}
    data, _ = _with_history(history=[HISTORY[1], older])
    rows = [c for c in data["courses"] if c["code"] == "CS2500"]
    assert len(rows) == 1
    assert (rows[0]["lastTerm"], rows[0]["terms"]) == ("Fall 2024", ["Fall 2024", "Fall 2023"])
    assert rows[0]["rating"] == 4.0 and rows[0]["numRatings"] == 1


def test_reviewed_course_without_history_has_no_terms():
    data, _ = _with_history()
    cs3500 = data["courses"][2]
    assert (cs3500["terms"], cs3500["lastTerm"], cs3500["hasPage"]) == ([], None, True)


def test_reviewed_course_missing_from_the_catalog_has_no_page():
    data, _, _ = _build()
    by_code = {c["code"]: c for c in data["courses"]}
    assert by_code["CS2500"]["hasPage"] is False   # course_name is None: no course_catalog row
    assert by_code["CS3500"]["hasPage"] is True


def test_last_taught_is_the_newest_history_row():
    data, _ = _with_history()
    assert data["lastTaught"] == "Fall 2026"


def test_no_history_means_no_last_taught():
    data, _ = _with_history(history=[])
    assert data["lastTaught"] is None
    assert [c["code"] for c in data["courses"]] == ["CS3500", "CS2500"]


def test_history_is_read_for_the_canonical_slug():
    _, calls = _with_history(slug="olin-guha", db=FakeDB(catalog={**CATALOG, "slug": "olin-guha-2"}))
    assert calls == ["olin-guha-2"]


def test_history_failure_leaves_courses_as_today(caplog):
    def broken(slug, query):
        raise RuntimeError("relation banner_course_instructors does not exist")

    data, _, _ = _build(history=broken)
    assert [c["code"] for c in data["courses"]] == ["CS3500", "CS2500"]
    assert all(c["terms"] == [] and c["lastTerm"] is None for c in data["courses"])
    assert data["lastTaught"] is None
    assert len([r for r in caplog.records if r.levelname == "ERROR"]) == 1


def test_history_failure_flags_the_payload_so_it_is_not_cached():
    def broken(slug, query):
        raise RuntimeError("banner down")

    data, _, _ = _build(history=broken)
    assert data["_partial"] is True


def test_history_success_has_no_failure_flag():
    data, _ = _with_history()
    assert "_partial" not in data


# ── student reviews ──

def test_survey_reviews_reach_the_payload():
    data, _, _ = _build(db=FakeDB(survey=[srow(), srow(comment="Hard but fair")]), review_id=lambda u: "abc")
    assert [r["comment"] for r in data["sources"]["survey"]["reviews"]] == ["Loved it", "Hard but fair"]


def test_survey_comments_are_sanitized():
    db = FakeDB(survey=[srow(comment="<script>x</script>hi")])
    data = build_payload("olin-guha", db.query, db.query_one, lambda t: t.replace("<script>x</script>", ""),
                         lambda *a: [], awards_for=lambda k: [], review_id=lambda u: "abc")
    assert data["sources"]["survey"]["reviews"][0]["comment"] == "hi"


def test_no_review_id_means_no_survey_cards():
    data, _, _ = _build(db=FakeDB(survey=[srow()]))
    assert data["sources"]["survey"]["reviews"] == []


def test_reviews_off_skips_the_survey_read_and_keeps_the_pipeline_count():
    summaries = [{**r, "num_comments": 8} if r["source"] == "blend" and r["course_code"] == "" else r
                 for r in SUMMARY_ROWS] + [{**SUMMARY_ROWS[0], "source": "survey", "num_comments": 5}]
    db = FakeDB(summaries=summaries, survey=[srow(), srow()])
    data, _, _ = _build(db=db)
    assert not any("survey_ratings" in sql for sql, _ in db.calls)
    assert data["summary"]["numComments"] == 8 + len(MENTIONS)


def test_num_comments_counts_live_survey_comments_not_the_stale_survey_row():
    # own rows: blend num_comments 8 (rmp 3 + a stale survey 5), survey num_comments 5; live: 2 comments
    summaries = [{**r, "num_comments": 8} if r["source"] == "blend" and r["course_code"] == "" else r
                 for r in SUMMARY_ROWS] + [{**SUMMARY_ROWS[0], "source": "survey", "num_comments": 5}]
    db = FakeDB(summaries=summaries, survey=[srow(), srow(), srow(comment=None)])
    data, _, _ = _build(db=db, review_id=lambda u: "abc")
    assert data["summary"]["numComments"] == 3 + 2 + len(MENTIONS)


def test_a_pending_course_comment_counts_like_its_card():
    # No course_code: the rating counts in no number, but its approved comment has a card.
    db = FakeDB(survey=[srow(), srow(course_code=None, course_name=None)])
    data, _, _ = _build(db=db, review_id=lambda u: "abc")
    assert len(data["sources"]["survey"]["reviews"]) == 2
    assert data["summary"]["numComments"] == 3 + 2 + len(MENTIONS)
    assert data["sources"]["survey"]["numRatings"] == 1


def test_student_numbers_are_live_and_replace_the_weekly_rows():
    # The weekly survey row says 9 ratings at 1.0; the live read has two 5s.
    summaries = SUMMARY_ROWS + [{**SUMMARY_ROWS[0], "source": "survey", "rating": 1.0, "num_ratings": 9}]
    db = FakeDB(summaries=summaries, survey=[srow(), srow(rating=3, comment=None)])
    data, _, _ = _build(db=db, review_id=lambda u: "abc")
    survey = data["sources"]["survey"]
    assert survey["available"] and survey["numRatings"] == 2 and survey["rating"] == 4.0
    assert survey["hoursPerWeek"] == 6.0 and survey["gradeDistribution"] == {"A": 2}
    assert data["summary"]["bySource"]["survey"] == {"rating": 4.0, "numRatings": 2}
    # rmp 57 at 4.2 blended with survey 2 at 4.0, weighted by count
    assert data["summary"]["numRatings"] == 59
    assert data["summary"]["rating"] == round((4.2 * 57 + 4.0 * 2) / 59, 2)
    cs3500 = next(c for c in data["courses"] if c["code"] == "CS3500")
    assert cs3500["numRatings"] == 4 and cs3500["name"] == "Object-Oriented Design" and cs3500["hasPage"]


def test_a_comment_awaiting_review_counts_in_the_numbers_but_has_no_card():
    # fetch_rows returns NULL for a comment no reviewer has approved.
    db = FakeDB(survey=[srow(comment=None, rating=1)])
    data, _, _ = _build(db=db, review_id=lambda u: "abc")
    assert data["sources"]["survey"]["reviews"] == []
    assert data["sources"]["survey"]["numRatings"] == 1
    assert data["summary"]["numRatings"] == 58
    assert data["summary"]["numComments"] == 3 + len(MENTIONS)


def test_a_failed_survey_read_keeps_the_weekly_numbers():
    summaries = SUMMARY_ROWS + [{**SUMMARY_ROWS[0], "source": "survey", "rating": 1.0, "num_ratings": 9}]
    data, _, _ = _build(db=FakeDB(summaries=summaries, survey=RuntimeError("boom")), review_id=lambda u: "abc")
    assert data["sources"]["survey"]["numRatings"] == 9 and data["summary"]["numRatings"] == 57


def test_missing_survey_table_is_no_reviews_and_stays_cacheable():
    db = FakeDB(survey=psycopg2.errors.UndefinedTable('relation "survey_ratings" does not exist'))
    data, _, _ = _build(db=db, review_id=lambda u: "abc")
    assert data["sources"]["survey"]["reviews"] == []
    assert "_partial" not in data


def test_missing_banner_table_in_the_survey_read_is_a_failure_not_no_reviews():
    db = FakeDB(survey=psycopg2.errors.UndefinedTable('relation "banner_terms" does not exist'))
    data, _, _ = _build(db=db, review_id=lambda u: "abc")
    assert data["_partial"] is True


def test_survey_read_failure_flags_the_payload_so_it_is_not_cached(caplog):
    data, _, _ = _build(db=FakeDB(survey=RuntimeError("boom")), review_id=lambda u: "abc")
    assert data["_partial"] is True and data["sources"]["survey"]["reviews"] == []
    assert len([r for r in caplog.records if r.levelname == "ERROR"]) == 1


# ── edge cases ──

def test_unrated_professor_is_all_null():
    empty = {"rating": None, "difficulty": None, "would_take_again_pct": None, "num_ratings": 0,
             "num_comments": 0, "rating_distribution": {}, "grade_distribution": {}}
    unrated = {**CATALOG, "avg_rating": None, "rmp_rating": None, "num_ratings": 0,
               "total_reviews": 0, "would_take_again_pct": None, "difficulty": None,
               "professor_url": None}
    summaries = [{**SUMMARY_ROWS[0], **empty}, {**SUMMARY_ROWS[1], **empty}]
    data, _, _ = _build(db=FakeDB(catalog=unrated, reviews=[], summaries=summaries), mentions=[])
    s = data["summary"]
    assert (s["rating"], s["difficulty"], s["wouldTakeAgainPct"], s["numRatings"]) == (None, None, None, 0)
    assert s["bySource"] == {"rmp": {"rating": None, "numRatings": 0}}
    rmp = data["sources"]["rmp"]
    assert rmp["available"] is False
    assert (rmp["rating"], rmp["difficulty"], rmp["wouldTakeAgainPct"]) == (None, None, None)
    assert data["courses"] == []


def test_banner_only_professor_payload():
    banner_only = {**CATALOG, "slug": "ada-newhire", "name": "Ada Newhire", "name_key": "ada newhire",
                   "avg_rating": None, "rmp_rating": None, "num_ratings": 0, "total_reviews": 0,
                   "would_take_again_pct": None, "difficulty": None, "professor_url": None,
                   "total_comments": 0}
    history = [{"code": "CS3100", "name": "Program Design and Implementation 2", "termsTaught": 1,
                "lastTerm": "Spring 2026", "recentTerms": ["Spring 2026"],
                "avgClassSize": 100, "hasPage": False}]
    data, _ = _with_history(history, slug="ada-newhire", db=FakeDB(catalog=banner_only, reviews=[], summaries=[]), mentions=[])
    assert data["sources"]["rmp"]["available"] is False
    assert data["sources"]["rmp"]["professorUrl"] is None
    assert data["summary"]["rating"] is None
    assert data["summary"]["numRatings"] == 0
    assert [c["code"] for c in data["courses"]] == ["CS3100"]
    assert data["lastTaught"] == "Spring 2026"


def test_zero_ratings_are_null_not_zero():
    zeros = [{**r, "rating": 0.0, "difficulty": 0.0} for r in SUMMARY_ROWS]
    data, _, _ = _build(db=FakeDB(summaries=zeros))
    assert data["summary"]["rating"] is None
    assert data["summary"]["difficulty"] is None


def test_zero_would_take_again_is_a_real_percentage():
    zeros = [{**r, "would_take_again_pct": 0.0} for r in SUMMARY_ROWS]
    data, _, _ = _build(db=FakeDB(summaries=zeros))
    assert data["summary"]["wouldTakeAgainPct"] == 0.0
    assert data["sources"]["rmp"]["wouldTakeAgainPct"] == 0.0


def test_alias_fallback_serves_the_canonical_slug():
    # No row has slug "olin-guha", so the lookup falls back to name_key "olin guha".
    db = FakeDB(catalog={**CATALOG, "slug": "olin-guha-2"})
    data, db, seen = _build(slug="olin-guha", db=db)
    assert data["identity"]["slug"] == "olin-guha-2"
    assert seen["slug"] == "olin-guha-2"


def test_missing_professor_is_none():
    data, _, _ = _build(slug="nobody", db=FakeDB())
    assert data is None


# ── round trips ──

def test_at_most_six_statements_and_only_live_tables():
    _, db, _ = _build(review_id=lambda u: "abc")
    assert len(db.calls) <= 6
    tables = " ".join(sql.lower() for sql, _ in db.calls)
    for table in ("professors_catalog", "rmp_reviews", "source_summary", "banner_course_instructors",
                  "survey_ratings"):
        assert table in tables
