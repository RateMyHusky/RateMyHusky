"""Course and instructor history built from stored Banner sections. Pure, no DB."""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
from banner_history import (MAX_COURSES_PER_TERM, academic_year,  # noqa: E402
                            build_course_instructors, build_course_offerings,
                            offering_pattern, pattern_window, rename_candidates,
                            roster_artifacts)

LABELS = {"202710": ("Fall 2026", "Fall"), "202630": ("Spring 2026", "Spring"),
          "202650": ("Summer Full 2026", "Summer"), "202610": ("Fall 2025", "Fall"),
          "202530": ("Spring 2025", "Spring"), "202510": ("Fall 2024", "Fall"),
          "202430": ("Spring 2024", "Spring"), "202410": ("Fall 2023", "Fall"),
          "202330": ("Spring 2023", "Spring"), "202310": ("Fall 2022", "Fall"),
          "202615": ("Fall 2025", "Fall"),
          "202325": ("Winter 2023", "Winter"), "202425": ("Winter 2024", "Winter"),
          "202525": ("Winter 2025", "Winter"), "202625": ("Winter 2026", "Winter")}


def sec(term, crn, course="CS3500", enrollment=30, cap=40, wait=0,
        schedule="Lecture", campus="Boston", method="Traditional",
        attributes=None, credits=4.0):
    label, group = LABELS[term]
    return {"term_code": term, "crn": crn, "subject": course[:-4],
            "subject_course": course, "course_title": f"Title {term}",
            "campus": campus, "instructional_method": method,
            "schedule_type": schedule, "credit_hours_low": credits,
            "credit_hours_high": None, "enrollment": enrollment,
            "max_enrollment": cap, "wait_count": wait, "attributes": attributes,
            "term_label": label, "season_group": group,
            "closed": term != "202710"}


def ins(term, crn, key="annie witte", course="CS3500", enrollment=30,
        schedule="Lecture", primary=True, campus="Boston"):
    label, _ = LABELS[term]
    return {"term_code": term, "crn": crn, "instructor_key": key,
            "instructor_name": key.title(), "instructor_email": None,
            "is_primary": primary, "subject_course": course,
            "schedule_type": schedule, "campus": campus,
            "instructional_method": "Traditional", "enrollment": enrollment,
            "term_label": label, "closed": term != "202710"}


def matcher(known):
    def match(key, course=None, term_codes=()):
        if key in known:
            return known[key], key, "name_key"
        return None, None, "no_match"
    return match


# ── academic year and the pattern window ─────────────────────────────────

def test_academic_year_groups_fall_with_the_following_spring_and_summer():
    assert academic_year("202610") == academic_year("202630") == academic_year("202650")
    assert academic_year("202710") == 2027


def test_pattern_window_drops_the_in_progress_year():
    closed = {"202710": False, "202630": True, "202610": True, "202530": True,
              "202430": True, "202330": True, "202230": True}
    assert pattern_window(closed) == [2023, 2024, 2025, 2026]


def test_pattern_window_keeps_the_newest_year_once_it_has_closed():
    """Found on the live 2026-10-01 sample: Summer 2026 alone in its year is
    a finished year, not an in-progress one."""
    assert pattern_window({"202655": True, "201952": True}) == [2026]


def test_pattern_window_skips_years_the_backfill_has_not_reached():
    closed = {"202630": True, "202330": True}
    assert pattern_window(closed) == [2023, 2026]


def test_pattern_window_is_empty_when_only_an_open_year_is_stored():
    assert pattern_window({"202710": False}) == []


# ── offering_pattern ─────────────────────────────────────────────────────

def test_pattern_names_every_regular_season():
    label, counts = offering_pattern({"Fall": {2023, 2024, 2025, 2026},
                                      "Spring": {2023, 2024, 2025, 2026}},
                                     [2023, 2024, 2025, 2026])
    assert label == "Fall and Spring"
    assert counts == {"Fall": 4, "Spring": 4, "Summer": 0}


def test_pattern_three_of_four_years_still_counts_as_regular():
    label, _ = offering_pattern({"Fall": {2023, 2024, 2026}}, [2023, 2024, 2025, 2026])
    assert label == "Fall"


def test_pattern_every_other_year_is_irregular():
    label, _ = offering_pattern({"Spring": {2024, 2026}}, [2023, 2024, 2025, 2026])
    assert label == "Irregular"


def test_pattern_outside_the_window_is_not_recent():
    label, counts = offering_pattern({"Fall": {2017, 2018}}, [2023, 2024, 2025, 2026])
    assert label == "Not offered recently"
    assert counts["Fall"] == 0


# ── roster artifacts ─────────────────────────────────────────────────────

def test_coordinator_on_too_many_courses_is_an_artifact_for_that_term_only():
    many = [ins("202630", str(i), key="lab coordinator", course=f"PHYS{1000 + i}")
            for i in range(MAX_COURSES_PER_TERM + 1)]
    normal = [ins("202610", "x", key="lab coordinator", course="PHYS1151")]
    assert roster_artifacts(many + normal) == {("202630", "lab coordinator")}


# ── build_course_instructors ─────────────────────────────────────────────

def test_course_instructor_history_counts_terms_and_sections():
    rows = [ins("202610", "1"), ins("202610", "2"), ins("202630", "3"), ins("202710", "4")]
    got = build_course_instructors(rows, matcher({"annie witte": "annie-witte"}))
    assert len(got) == 1
    r = got[0]
    assert (r["terms_taught"], r["sections"]) == (3, 4)
    assert (r["first_term_code"], r["last_term_code"]) == ("202610", "202710")
    assert r["last_term_label"] == "Fall 2026"
    assert r["recent_terms"] == "Fall 2026,Spring 2026,Fall 2025"
    assert r["professor_slug"] == "annie-witte"


def test_class_size_only_reads_closed_terms_with_real_headcounts():
    rows = [ins("202610", "1", enrollment=20), ins("202630", "2", enrollment=40),
            ins("202630", "3", enrollment=0),           # cancelled, kept by Banner
            ins("202710", "4", enrollment=5)]           # open: a snapshot
    got = build_course_instructors(rows, matcher({}))
    assert got[0]["avg_enrollment"] == 30.0


def test_unmatched_instructors_are_kept_without_a_slug():
    got = build_course_instructors([ins("202610", "1", key="new person")], matcher({}))
    assert got[0]["professor_slug"] is None
    assert got[0]["match_method"] == "no_match"


def test_individual_instruction_is_not_history():
    rows = [ins("202610", "1", schedule="Individual Instruction")]
    assert build_course_instructors(rows, matcher({})) == []


def test_roster_artifacts_are_excluded_from_history():
    rows = [ins("202630", str(i), key="lab coordinator", course=f"PHYS{1000 + i}")
            for i in range(MAX_COURSES_PER_TERM + 1)]
    assert build_course_instructors(rows, matcher({})) == []


def test_co_teachers_each_get_a_row():
    rows = [ins("202610", "1"), ins("202610", "1", key="patrick hurley", primary=False)]
    got = build_course_instructors(rows, matcher({}))
    assert {(r["instructor_key"], r["was_primary"]) for r in got} == {
        ("annie witte", True), ("patrick hurley", False)}


def test_non_place_campus_is_dropped():
    rows = [ins("202610", "1", campus="No campus, no room needed"),
            ins("202630", "2", campus="Online")]
    assert build_course_instructors(rows, matcher({}))[0]["campuses"] == "Online"


# ── build_course_offerings ───────────────────────────────────────────────

def history(course="CS3500"):
    """Fall and Spring every year 2022-2026, plus the open Fall 2026."""
    return [sec(t, f"{t}-{i}", course=course)
            for t in ("202310", "202330", "202410", "202430", "202510",
                      "202530", "202610", "202630", "202710")
            for i in range(2)]


def test_offering_reports_pattern_and_window_counts():
    got = build_course_offerings(history())[0]
    assert got["pattern"] == "Fall and Spring"
    assert (got["fall_years"], got["spring_years"], got["summer_years"]) == (4, 4, 0)
    assert got["pattern_window_years"] == 4
    assert got["terms_offered"] == 9
    assert got["avg_sections_per_term"] == 2.0


def test_offering_only_in_the_open_year_is_new():
    assert build_course_offerings([sec("202710", "1", course="CS4999")])[0]["pattern"] == "New"


def test_offering_marks_what_is_on_the_current_schedule():
    assert build_course_offerings(history())[0]["offered_now"] == "Fall 2026"


def test_offering_credit_hours_formats_fixed_and_variable():
    assert build_course_offerings([sec("202610", "1", credits=4.0)])[0]["credit_hours"] == "4"
    variable = sec("202610", "1", credits=1.0)
    variable["credit_hours_high"] = 4.0
    assert build_course_offerings([variable])[0]["credit_hours"] == "1-4"


def test_offering_leaves_registration_facts_to_searchneu():
    """Seats, waitlists, requirements and course format are SearchNEU's job."""
    got = build_course_offerings(history())[0]
    for field in ("avg_capacity", "fill_rate", "waitlisted_share",
                  "nupath", "campuses", "methods", "usual_format"):
        assert field not in got


def test_offering_title_comes_from_the_newest_term():
    assert build_course_offerings(history())[0]["course_title"] == "Title 202710"


def test_offering_class_size_uses_closed_terms():
    secs = [sec("202610", "1", enrollment=40, cap=40, wait=5),
            sec("202630", "2", enrollment=20, cap=40),
            sec("202710", "3", enrollment=1, cap=100, wait=50)]   # open: ignored
    got = build_course_offerings(secs)[0]
    assert got["avg_section_size"] == 30.0
    assert got["median_section_size"] == 30.0


def test_offering_tba_sections_still_count():
    """build_course_offerings reads sections, not instructors."""
    got = build_course_offerings([sec("202610", "1"), sec("202610", "2")], [])[0]
    assert got["avg_sections_per_term"] == 2.0
    assert got["instructor_count"] == 0


def test_offering_counts_distinct_instructors_without_artifacts():
    secs = [sec("202610", "1"), sec("202630", "2")]
    rows = [ins("202610", "1"), ins("202630", "2"), ins("202630", "2", key="patrick hurley")]
    assert build_course_offerings(secs, rows)[0]["instructor_count"] == 2


def test_offering_skips_individual_instruction_only_courses():
    secs = [sec("202610", "1", course="CS9990", schedule="Individual Instruction")]
    assert build_course_offerings(secs) == []


def test_law_and_cps_share_a_label_with_the_main_term():
    """Fall 2025 Semester and Fall 2025 CPS Quarter are one term to a student."""
    secs = [sec("202610", "1"), sec("202615", "2")]
    assert build_course_offerings(secs)[0]["terms_offered"] == 1


# ── rename candidates ────────────────────────────────────────────────────

def offering(code, title, first, last, label="Spring 2023"):
    return {"subject_course": code, "subject": re.match(r"[A-Z]+", code).group(),
            "course_title": title, "first_term_code": first, "last_term_code": last,
            "last_term_label": label}


def taught(code, key):
    return {"subject_course": code, "instructor_key": key, "instructor_name": key.title()}



def test_renumbered_course_with_a_shared_instructor_is_a_candidate():
    offs = [offering("ECON1291", "Development Economics", "202210", "202330"),
            offering("ECON3291", "Development Economics", "202410", "202710")]
    got = rename_candidates(offs, [taught("ECON1291", "x y"), taught("ECON3291", "x y")])
    assert [(c["old_code"], c["new_code"], c["same_subject"]) for c in got] == [
        ("ECON1291", "ECON3291", True)]


def test_no_shared_instructor_no_candidate():
    offs = [offering("ECON1291", "Development Economics", "202210", "202330"),
            offering("ECON3291", "Development Economics", "202410", "202710")]
    assert rename_candidates(offs, [taught("ECON1291", "a b"), taught("ECON3291", "c d")]) == []


def test_cross_listings_running_together_are_not_candidates():
    offs = [offering("AFCS1225", "Gender, Race, and Medicine", "202210", "202710"),
            offering("HIST1225", "Gender, Race, and Medicine", "202210", "202710")]
    rows = [taught("AFCS1225", "x y"), taught("HIST1225", "x y")]
    assert rename_candidates(offs, rows) == []


def test_generic_titles_are_never_candidates():
    offs = [offering("INAM5963", "Topics", "202210", "202330"),
            offering("CS5963", "Topics", "202410", "202710")]
    rows = [taught("INAM5963", "x y"), taught("CS5963", "x y")]
    assert rename_candidates(offs, rows) == []


# ── cancelled sections ───────────────────────────────────────────────────

def test_a_cancelled_section_does_not_count_as_taught():
    """The reviewer's repro: one closed-term section with 0 enrolled gave
    terms_taught=1 and last_term='Spring 2024'."""
    rows = [ins("202430", "1", enrollment=0)]
    assert build_course_instructors(rows, matcher({})) == []


def test_a_cancelled_section_does_not_set_the_last_term():
    rows = [ins("202330", "1"), ins("202430", "2", enrollment=0)]
    got = build_course_instructors(rows, matcher({}))[0]
    assert (got["terms_taught"], got["last_term_label"]) == (1, "Spring 2023")


def test_a_course_whose_every_section_was_cancelled_is_not_offered():
    """Four years of 0-enrollment sections used to read as offered every Spring."""
    secs = [sec(t, "1", enrollment=0) for t in ("202330", "202430", "202530", "202630")]
    secs.append(sec("202630", "9", course="CS2500"))
    assert [o["subject_course"] for o in build_course_offerings(secs)] == ["CS2500"]


def test_zero_enrolled_in_an_open_term_still_counts():
    """Registration hasn't filled it yet; that's not a cancellation."""
    got = build_course_offerings([sec("202710", "1", enrollment=0)])
    assert got[0]["offered_now"] == "Fall 2026"


# ── CPS Winter quarter ───────────────────────────────────────────────────

def test_a_winter_quarter_course_counts_as_spring():
    """MGT5000 ran every Winter quarter and read 'Not offered recently'."""
    secs = [sec(t, "1", course="MGT5000") for t in ("202325", "202425", "202525", "202625")]
    secs += [sec(t, "2", course="CS2500") for t in ("202330", "202430", "202530", "202630")]
    got = {o["subject_course"]: o for o in build_course_offerings(secs)}
    assert got["MGT5000"]["pattern"] == "Spring"
    assert got["MGT5000"]["spring_years"] == 4


def test_match_gets_the_course_and_terms_it_is_judging():
    seen = []

    def match(key, course, term_codes):
        seen.append((key, course, term_codes))
        return None, None, "no_match"

    build_course_instructors([ins("202630", "1"), ins("202610", "2")], match)
    assert seen == [("annie witte", "CS3500", {"202630", "202610"})]
