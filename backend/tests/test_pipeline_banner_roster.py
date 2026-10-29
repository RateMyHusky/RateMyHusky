from pipeline import banner_roster as br

def bci(key, course, name, method="no_match", slug=None, terms=1, last="202630"):
    return {"subject_course": course, "instructor_key": key, "instructor_name": name,
            "professor_slug": slug, "match_method": method, "terms_taught": terms,
            "last_term_code": last}

PROFS = [{"slug": "john-smith", "name": "John Smith", "name_key": "john smith"},
         {"slug": "ada-park", "name": "Ada Park", "name_key": "ada park"}]
DEPTS = {"CS": "Computer Science", "MATH": "Mathematics"}
never = lambda key: False


def test_no_match_instructor_becomes_a_banner_professor():
    rows, counts = br.resolve_banner_professors(
        [bci("lucia nunez", "CS3100", "Nunez, Lucia", terms=3),
         bci("lucia nunez", "MATH1365", "Nunez, Lucia", terms=1)], PROFS, DEPTS, never)
    assert rows == [{"slug": "lucia-nunez", "name": "Lucia Nunez", "name_key": "lucia nunez",
                     "department": "Computer Science", "college": br.get_college("Computer Science"),
                     "image_url": None, "focus_x": None, "focus_y": None, "origin": "banner"}]
    assert counts["created"] == 1


def test_only_no_match_rows_create_professors():
    rows, _ = br.resolve_banner_professors(
        [bci("wei wang", "CHEM1211", "Wang, Wei", method=m)
         for m in ("ambiguous", "subject_mismatch", "alias_unverified", "roster_duplicate")],
        PROFS, DEPTS, never)
    assert rows == []


def test_a_key_mixing_no_match_with_another_verdict_is_skipped():
    rows, counts = br.resolve_banner_professors(
        [bci("wei wang", "CHEM1211", "Wang, Wei"),
         bci("wei wang", "CHEM2311", "Wang, Wei", method="roster_duplicate")], PROFS, DEPTS, never)
    assert rows == [] and counts["mixed"] == 1


def test_existing_name_key_is_known_not_created():
    rows, counts = br.resolve_banner_professors(
        [bci("ada park", "CS2500", "Park, Ada")], PROFS, DEPTS, never)
    assert rows == [] and counts["known"] == 1


def test_middle_name_matching_first_and_last_is_a_possible_duplicate():
    rows, counts = br.resolve_banner_professors(
        [bci("john a smith", "CS2500", "Smith, John A")], PROFS, DEPTS, never)
    assert rows == [] and counts["possible_duplicate"] == 1


def test_denied_names_are_never_created():
    rows, counts = br.resolve_banner_professors(
        [bci("lucia nunez", "CS3100", "Nunez, Lucia")], PROFS, DEPTS, lambda k: k == "lucia nunez")
    assert rows == [] and counts["denied"] == 1


def test_slug_collision_gets_a_suffix():
    profs = PROFS + [{"slug": "lucia-nunez", "name": "Lucia Nunez", "name_key": "lucia nunez x"}]
    rows, _ = br.resolve_banner_professors([bci("lucia nunez", "CS3100", "Nunez, Lucia")],
                                           profs, DEPTS, never)
    assert rows[0]["slug"] == "lucia-nunez-2"


def test_newest_spelling_names_the_professor():
    rows, _ = br.resolve_banner_professors(
        [bci("lucia nunez", "CS3100", "Nunez, L", last="202530"),
         bci("lucia nunez", "CS3200", "Nunez, Lucia", last="202710")], PROFS, DEPTS, never)
    assert rows[0]["name"] == "Lucia Nunez"


def test_unknown_subject_leaves_department_empty():
    rows, _ = br.resolve_banner_professors([bci("lucia nunez", "ZZZZ1000", "Nunez, Lucia")],
                                           PROFS, DEPTS, never)
    assert rows[0]["department"] is None and rows[0]["college"] == br.get_college(None)


def test_rerun_after_insert_creates_nothing():
    first, _ = br.resolve_banner_professors([bci("lucia nunez", "CS3100", "Nunez, Lucia")],
                                            PROFS, DEPTS, never)
    again, counts = br.resolve_banner_professors([bci("lucia nunez", "CS3100", "Nunez, Lucia")],
                                                 PROFS + first, DEPTS, never)
    assert again == [] and counts["known"] == 1


def test_subject_departments_takes_the_majority_and_ignores_unmatched():
    rows = [bci("a", "CS2500", "A", slug="p1"), bci("b", "CS3500", "B", slug="p2"),
            bci("c", "CS1800", "C", slug="p3"), bci("d", "CS9999", "D")]
    depts = {"p1": "Computer Science", "p2": "Computer Science", "p3": "Mathematics"}
    assert br.subject_departments(rows, depts) == {"CS": "Computer Science"}


def test_banner_key_without_middle_name_is_a_duplicate_of_a_middle_name_professor():
    profs = PROFS + [{"slug": "john-a-smith", "name": "John A Smith", "name_key": "john a smith"}]
    rows, counts = br.resolve_banner_professors(
        [bci("john smith", "CS2500", "Smith, John")], profs[2:], DEPTS, never)
    assert rows == [] and counts["possible_duplicate"] == 1


def test_two_banner_only_keys_differing_by_middle_name_create_one_page():
    rows, counts = br.resolve_banner_professors(
        [bci("john a smith", "CS2500", "Smith, John A"), bci("john smith", "CS2500", "Smith, John")],
        [], DEPTS, never)
    assert [r["name_key"] for r in rows] == ["john a smith"]
    assert counts["created"] == 1 and counts["possible_duplicate"] == 1


def test_fully_matched_key_is_matched_not_mixed():
    rows, counts = br.resolve_banner_professors(
        [bci("wei wang", "CHEM1211", "Wang, Wei", method="ambiguous")], PROFS, DEPTS, never)
    assert rows == [] and counts["matched"] == 1 and counts["mixed"] == 0


def test_generational_suffix_matching_an_existing_professor_is_a_possible_duplicate():
    profs = PROFS + [{"slug": "martin-schwarz-jr", "name": "Martin Schwarz, Jr.",
                      "name_key": "martin schwarz, jr."}]
    rows, counts = br.resolve_banner_professors(
        [bci("richard melloni jr", "PSYC1101", "Melloni Jr, Richard"),
         bci("martin schwarz jr", "MATH1341", "Schwarz Jr, Martin")],
        profs + [{"slug": "richard-melloni", "name": "Richard Melloni", "name_key": "richard melloni"}],
        DEPTS, never)
    assert rows == [] and counts["possible_duplicate"] == 2


def test_banner_key_aliased_to_a_denied_professor_is_denied(monkeypatch):
    monkeypatch.setattr(br, "BANNER_ALIASES", {"wan yee yvonne leung": "yvonne leung"})
    monkeypatch.setattr(br, "is_denied", lambda name: False)
    monkeypatch.setattr(br, "is_denied_key", lambda key: key == "yvonne leung")
    assert br.is_denied_banner_key("wan yee yvonne leung")
    assert br.is_denied_banner_key("yvonne leung")              # the key itself, unresolved
    assert not br.is_denied_banner_key("lucia nunez")


def test_banner_key_denied_through_alias_map(monkeypatch):
    seen = []
    monkeypatch.setattr(br, "is_denied", lambda name: seen.append(name) or True)
    assert br.is_denied_banner_key("virgiliu pavlu") and seen == ["virgiliu pavlu"]


def track(key, track_name, sections, slug=None):
    return {"instructor_key": key, "professor_slug": slug, "track": track_name, "sections": sections}


def test_majority_law_or_cps_quarter_track_names_the_college():
    colleges = br.track_colleges([track("ada park", "Law Semester", 6, "ada-park"),
                                  track("ada park", "Semester", 2, "ada-park"),
                                  track("john smith", "CPS Quarter", 3, "john-smith")], {})
    assert colleges == {"ada-park": "Law", "john-smith": "Professional Studies"}


def test_day_college_majority_or_a_tie_keeps_the_department_college():
    colleges = br.track_colleges([track("ada park", "CPS Quarter", 2, "ada-park"),
                                  track("ada park", "Semester", 3, "ada-park"),
                                  track("john smith", "Law Semester", 2, "john-smith"),
                                  track("john smith", "Semester", 2, "john-smith")], {})
    assert colleges == {}


def test_cps_semester_does_not_count_toward_professional_studies():
    # Day-college subjects taught to CPS undergraduates by day-college faculty.
    assert br.track_colleges([track("ada park", "CPS Semester", 9, "ada-park")], {}) == {}


def test_sections_are_summed_across_a_professors_instructor_keys():
    colleges = br.track_colleges([track("ada park", "Law Semester", 2, "ada-park"),
                                  track("ada park", "Semester", 3, "ada-park"),
                                  track("ada m park", "Law Semester", 2, "ada-park")], {})
    assert colleges == {"ada-park": "Law"}


def test_a_namesakes_unlinked_courses_do_not_count():
    # The matcher linked john smith's CS courses but refused his LAW ones as
    # another person's; those rows arrive with no slug and must not move him.
    colleges = br.track_colleges([track("john smith", "Semester", 2, "john-smith"),
                                  track("john smith", "Law Semester", 10)], {})
    assert colleges == {}


def test_unlinked_rows_count_for_a_banner_professor_created_this_run():
    assert br.track_colleges([track("lucia nunez", "CPS Quarter", 4)],
                             {"lucia nunez": "lucia-nunez"}) == {"lucia-nunez": "Professional Studies"}
    assert br.track_colleges([track("nobody", "Law Semester", 5)], {}) == {}


def test_track_sql_applies_the_banner_history_filters():
    sql = br.TRACK_SECTIONS_SQL
    assert "i.source = 'banner'" in sql
    assert all(f"'{t}'" in sql for t in br.NON_TEACHING_SCHEDULE_TYPES)
    assert f"> {br.MAX_COURSES_PER_TERM}" in sql
    assert "banner_roster_duplicates" in sql and "scraped_closed" in sql


def test_cancelled_sections_count_toward_the_coordinator_limit():
    # banner_history.roster_artifacts counts courses before dropping cancelled
    # sections, so the filter must come after the coordinators CTE, not in taught.
    sql = br.TRACK_SECTIONS_SQL
    taught = sql[:sql.index("coordinators AS")]
    assert "NOT t.cancelled" not in taught and "NOT (" not in taught
    assert sql.index("NOT t.cancelled") > sql.index("coordinators AS")


def test_track_sql_joins_every_merged_spelling_and_counts_each_section_once():
    sql = br.TRACK_SECTIONS_SQL
    # The reviewer's case: sections under an older spelling ("williams tom") must
    # reach the row the matcher kept under the newest one ("williams thomas").
    assert "string_to_array(coalesce(b.instructor_keys, b.instructor_key), '|')" in sql
    assert "count(DISTINCT (t.term_code, t.crn))" in sql


def test_track_sql_counts_law_courses_as_law_semester_in_any_term():
    # Law moved onto the Semester calendar in Fall 2025; other sections after
    # the last CPS Quarter term are set apart.
    sql = " ".join(br.TRACK_SECTIONS_SQL.split())
    assert ("CASE WHEN subject = 'LAW' THEN 'Law Semester' "
            "WHEN term_track = 'Law Semester' THEN term_track WHEN subject IN") in sql
    assert ("WHEN term_code > '202655' "
            "THEN 'After CPS Quarter' ELSE term_track END AS track") in sql


def test_sections_after_the_last_quarter_do_not_tip_a_cps_professor_out():
    # The reviewer's case: 6 quarter sections, then 2 Semester sections a term.
    rows = [track(None, "CPS Quarter", 6, "adj"), track(None, "After CPS Quarter", 8, "adj")]
    assert br.track_colleges(rows, {}) == {"adj": "Professional Studies"}


def test_sections_after_the_last_quarter_still_count_against_law():
    rows = [track(None, "Law Semester", 3, "ada"), track(None, "After CPS Quarter", 4, "ada")]
    assert br.track_colleges(rows, {}) == {}


def prof(slug, college, department="Law", origin="rmp"):
    return {"slug": slug, "college": college, "department": department, "origin": origin}


def bci_row(slug, course, sections):
    return {"professor_slug": slug, "subject_course": course, "sections": sections}


def test_a_law_label_with_no_law_sections_moves_to_its_subjects_college():
    exits = br.track_exits([track(None, "Semester", 6, "ada-park")], {},
                           [prof("ada-park", "Law")],
                           [bci_row("ada-park", "CRIM2100", 4), bci_row("ada-park", "BLAW3100", 2)],
                           {"CRIM": "CSSH", "BLAW": "Business"})
    assert exits == {"ada-park": "CSSH"}


def test_any_section_in_the_labels_track_keeps_it():
    # Law faculty who also teach a day-college course: a judgment the data can't make.
    exits = br.track_exits([track(None, "Semester", 6, "ada-park"),
                            track(None, "Law Semester", 1, "ada-park")], {},
                           [prof("ada-park", "Law")], [bci_row("ada-park", "CRIM2100", 7)],
                           {"CRIM": "CSSH"})
    assert exits == {}


def test_a_banner_only_professor_created_this_run_is_exited():
    # Unlinked until apply time: both their sections and their subjects come
    # through new_slug_by_key.
    exits = br.track_exits([track("park ada", "Semester", 4)], {"park ada": "ada-park"},
                           [prof("ada-park", "Law", origin="banner")],
                           [{"professor_slug": None, "instructor_key": "park ada",
                             "subject_course": "CRIM2100", "sections": 4}],
                           {"CRIM": "CSSH"})
    assert exits == {"ada-park": "CSSH"}


def test_no_banner_record_keeps_the_label():
    assert br.track_exits([], {}, [prof("ada-park", "Law")], [], {"CRIM": "CSSH"}) == {}


def test_professional_studies_labels_are_not_exited():
    # Applied Psychology faculty labelled Professional Studies would vote into CSSH.
    exits = br.track_exits([track(None, "Semester", 5, "john-smith")], {},
                           [prof("john-smith", "Professional Studies", "Counseling & Educational Psych")],
                           [bci_row("john-smith", "CAEP6200", 5)], {"CAEP": "CSSH"})
    assert exits == {}


def test_subjects_pointing_back_or_nowhere_keep_the_label():
    rows = [track(None, "Semester", 3, s) for s in ("a", "b", "c")]
    exits = br.track_exits(rows, {}, [prof("a", "Law"), prof("b", "Law"), prof("c", "Law")],
                           [bci_row("a", "LAWS6100", 3), bci_row("b", "INTL1000", 3),
                            bci_row("c", "XYZ1000", 3)],
                           {"LAWS": "Law", "INTL": "Other"})
    assert exits == {}


def test_a_law_label_teaching_cps_subjects_exits_to_professional_studies():
    # Andrew Guisbond's case: MGT is "Management - CPS", not Business's MGMT.
    exits = br.track_exits([track(None, "CPS Semester", 11, "ag")], {}, [prof("ag", "Law")],
                           [bci_row("ag", "MGT3100", 11)], {"MGT": "Professional Studies"})
    assert exits == {"ag": "Professional Studies"}


def test_cps_subjects_are_professional_studies_whoever_votes(monkeypatch):
    monkeypatch.setattr(br, "get_college", {"Management": "Business"}.get)
    rows = [{"professor_slug": "m1", "subject_course": "MGT3100"},
            {"professor_slug": "m1", "subject_course": "MGMT3100"}]
    assert br.subject_colleges(rows, [prof("m1", "Business", "Management")]) == {
        "MGT": "Professional Studies", "MGMT": "Business"}


def test_other_colleges_are_never_exited():
    exits = br.track_exits([track(None, "Law Semester", 0, "ada-park"),
                            track(None, "Semester", 4, "ada-park")], {},
                           [prof("ada-park", "Khoury", "Computer Science")],
                           [bci_row("ada-park", "CRIM2100", 4)], {"CRIM": "CSSH"})
    assert exits == {}


def test_track_labelled_professors_do_not_vote_on_a_subjects_college(monkeypatch):
    # Mislabelled Law professors teaching BLAW must not make BLAW a Law subject.
    monkeypatch.setattr(br, "get_college", {"Law": "Law", "Business Law": "Business"}.get)
    rows = [{"professor_slug": s, "subject_course": "BLAW3100"} for s in ("l1", "l2", "b1")]
    profs = [prof("l1", "Law"), prof("l2", "Law"), prof("b1", "Business", "Business Law")]
    assert br.subject_colleges(rows, profs) == {"BLAW": "Business"}


def test_track_sql_counts_cps_subjects_as_cps_quarter_in_any_term():
    # CPS Quarter ends after Summer 2026; its subjects stand in for it.
    sql = " ".join(br.TRACK_SECTIONS_SQL.split())
    assert "WHEN subject IN (SELECT subject FROM cps_subjects) THEN 'CPS Quarter'" in sql
    # A regex, not an int cast: a course number past int range would abort the query.
    assert "AND subject_course ~* '^[a-z]+([5-9][0-9]{3}|[1-9][0-9]{4,})' THEN 'CPS Quarter'" in sql


def test_the_cps_vote_counts_the_same_teaching_sections():
    sql = br.TRACK_SECTIONS_SQL
    cps = sql[sql.index("cps_subjects AS"):sql.index("taught AS")]
    assert "FROM listed" in cps and "NOT cancelled" in cps and "count(DISTINCT (term_code, crn))" in cps


def test_the_cps_vote_cutoff_is_pinned_to_the_last_quarter():
    sql = br.TRACK_SECTIONS_SQL
    cps = sql[sql.index("cps_subjects AS"):sql.index("taught AS")]
    assert f"term_code <= '{br.CPS_QUARTER_LAST_TERM}'" in cps and "max(term_code)" not in cps


def test_the_vote_rows_are_split_from_the_track_rows():
    rows = [{"instructor_key": None, "professor_slug": None, "track": None, "sections": None,
             "cps_subject": "PJM", "cps_share": 0.9},
            {"instructor_key": None, "professor_slug": "a", "track": "CPS Quarter", "sections": 2,
             "cps_subject": None, "cps_share": None}]
    assert br.split_cps_vote(rows) == ([rows[1]], frozenset({"PJM"}))


def test_only_voted_subjects_close_to_the_bar_are_named():
    # ITC clears the bar at 58% on production; a backfill could take it under.
    rows = [{"cps_subject": s, "cps_share": share} for s, share in (("PJM", 0.9), ("ITC", 0.58))]
    rows.append({"cps_subject": None, "cps_share": None})
    assert br.cps_vote_near_bar(rows) == {"ITC": 0.58}


def test_voted_cps_subjects_are_professional_studies_in_the_subject_vote(monkeypatch):
    # ESL left the catalog but the track counts it as CPS; the exits must agree.
    monkeypatch.setattr(br, "get_college", {"English": "CSSH"}.get)
    rows = [{"professor_slug": "e1", "subject_course": "ESL5100"}]
    profs = [prof("e1", "CSSH", "English")]
    assert br.subject_colleges(rows, profs) == {"ESL": "CSSH"}
    assert br.subject_colleges(rows, profs, br.CPS_SUBJECTS | {"ESL"}) == {"ESL": "Professional Studies"}
