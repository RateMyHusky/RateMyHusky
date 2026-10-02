"""Banner instructor -> professors_catalog matching.

The scrape is a solved 9-minute job; this file is where the feature can actually
lie to someone. A wrong match puts a course on the wrong professor's public
profile, so every ambiguous case must land in banner_unmatched instead of being
guessed.
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "backend")))
from match_banner_instructors import (BANNER_ALIASES, MIN_KEPT_RATIO,  # noqa: E402
                                      TEACHING_DDL, UNMATCHED_DDL,
                                      MatchGateFailed, build_rows,
                                      catalog_index, check_match_gate,
                                      group_instructors, match_one,
                                      single_term_desc, write_results)

SCRAPED = "2026-08-04T00:00:00"


@pytest.fixture
def cur():
    conn = sqlite3.connect(":memory:")
    c = conn.cursor()
    c.execute("""CREATE TABLE professors_catalog (
        slug TEXT PRIMARY KEY, name TEXT, name_key TEXT)""")
    c.executemany(
        "INSERT INTO professors_catalog (slug, name, name_key) VALUES (?, ?, ?)",
        [("annie-witte", "Annie Witte", "annie witte"),
         ("patrick-hurley", "Patrick Hurley", "patrick hurley"),
         ("john-smith", "John Smith", "john smith")])
    return c


@pytest.fixture
def store_cur():
    """professor_teaching + banner_unmatched only — write_results doesn't touch
    professors_catalog, so the `cur` fixture's catalog table would be noise."""
    conn = sqlite3.connect(":memory:")
    c = conn.cursor()
    for ddl in (TEACHING_DDL, UNMATCHED_DDL):
        for stmt in ddl.split(";"):
            if stmt.strip():
                c.execute(stmt.replace("TIMESTAMPTZ", "TIMESTAMP"))
    return c


def teaching_row(slug="annie-witte", key="annie witte", term_desc="Fall 2026",
                 term_codes="202710", courses="CS1000", campuses="Boston",
                 method="name_key", scraped_at=SCRAPED):
    return (slug, key, term_desc, term_codes, courses, campuses, method, scraped_at)


def brow(key="annie witte", course="ACCT1201", schedule="Lecture",
         campus="Boston", term="202710", name="Witte, Annie"):
    return {"instructor_key": key, "instructor_name": name,
            "subject_course": course,
            "schedule_type": schedule, "campus": campus, "term_code": term}


def test_catalog_index_maps_name_key_to_slug(cur):
    index = catalog_index(cur)
    assert index["annie witte"] == [("annie-witte", "annie witte")]


def test_match_exact_name_key(cur):
    slug, name_key, method, candidates = match_one("annie witte", catalog_index(cur))
    assert (slug, name_key, method, candidates) == \
        ("annie-witte", "annie witte", "name_key", [])


def test_match_has_no_fallback_beyond_alias(cur):
    """A middle initial the catalog doesn't have used to fall back to a
    middle-initial strip. That fallback is gone: it's ambiguity-blind (the
    catalog's sole "john smith" might be a different person from Banner's
    "john a smith"), and it was measured at zero real matches. Confirm it
    reports no_match rather than guessing."""
    slug, _, method, _ = match_one("john a smith", catalog_index(cur))
    assert (slug, method) == (None, "no_match")


def test_no_match_is_reported_not_guessed(cur):
    slug, _, method, candidates = match_one("brand new person", catalog_index(cur))
    assert (slug, method, candidates) == (None, "no_match", [])


# ── BANNER_ALIASES ────────────────────────────────────────────────────────
# Deliberately NOT folded into prof_aliases.ALIAS_MAP. That map is site-wide:
# the backend resolves every professor's name_key through it. These keys are
# *Banner* spellings that no catalog row ever contained, so putting them in
# ALIAS_MAP would make the whole site depend on how NUBanner happens to spell
# a name. Kept here, they take effect on a matcher re-run alone — no
# re-scrape, no catalog rebuild.

def test_banner_alias_resolves_a_banner_only_spelling(cur):
    cur.execute("INSERT INTO professors_catalog (slug, name, name_key) VALUES "
                "('phil-gasper', 'Phil Gasper', 'phil gasper')")
    slug, name_key, method, _ = match_one("philip gasper", catalog_index(cur))
    assert (slug, name_key, method) == ("phil-gasper", "phil gasper", "banner_alias")


def test_banner_alias_resolves_a_banner_only_middle_name(cur):
    """Banner carries a middle name or second surname the RMP-built catalog
    drops. Curated per person, never a general strip — see match_one."""
    cur.execute("INSERT INTO professors_catalog (slug, name, name_key) VALUES "
                "('najla-mouchrek', 'Najla Mouchrek', 'najla mouchrek')")
    slug, _, method, _ = match_one("najla miranda mouchrek", catalog_index(cur))
    assert (slug, method) == ("najla-mouchrek", "banner_alias")


def test_exact_name_key_wins_over_a_banner_alias(cur):
    """Order matters: a real catalog row spelled exactly as Banner spells it is
    always the better answer than following a curated variant."""
    cur.execute("INSERT INTO professors_catalog (slug, name, name_key) VALUES "
                "('philip-gasper', 'Philip Gasper', 'philip gasper'), "
                "('phil-gasper', 'Phil Gasper', 'phil gasper')")
    slug, _, method, _ = match_one("philip gasper", catalog_index(cur))
    assert (slug, method) == ("philip-gasper", "name_key")


def test_banner_alias_ambiguity_is_reported_not_guessed(cur):
    """Same contract as the ALIAS_MAP path: two catalog rows at the aliased key
    means the person is not identifiable, so it must land in banner_unmatched
    with both candidates rather than pick one."""
    cur.execute("INSERT INTO professors_catalog (slug, name, name_key) VALUES "
                "('phil-gasper', 'Phil Gasper', 'phil gasper'), "
                "('phil-gasper-2', 'Phil Gasper', 'phil gasper')")
    slug, _, method, candidates = match_one("philip gasper", catalog_index(cur))
    assert (slug, method) == (None, "ambiguous")
    assert sorted(candidates) == ["phil-gasper", "phil-gasper-2"]


def test_banner_aliases_do_not_overlap_alias_map():
    """If a key lived in both maps, which one won would depend on the order of
    the tuple in match_one — a silent behaviour change waiting for whoever
    reorders it. Forbid the overlap instead of relying on the order.
    """
    from prof_aliases import ALIAS_MAP
    both = sorted(set(BANNER_ALIASES) & set(ALIAS_MAP))
    assert both == [], f"keys in both maps: {both}"


def test_banner_aliases_are_not_chained():
    """Neither within BANNER_ALIASES nor across into ALIAS_MAP. match_one does a
    single lookup, so a -> b -> c would silently resolve only to b.
    """
    from prof_aliases import ALIAS_MAP
    internal = sorted(set(BANNER_ALIASES.values()) & set(BANNER_ALIASES.keys()))
    assert internal == [], f"chained within BANNER_ALIASES: {internal}"
    into_alias = sorted(set(BANNER_ALIASES.values()) & set(ALIAS_MAP.keys()))
    assert into_alias == [], f"target is an ALIAS_MAP key: {into_alias}"


def test_banner_aliases_are_normalized_like_instructor_keys():
    """The lookup is match_one(instructor_key), and instructor_key comes from
    normalize_instructor_key — lowercase, ascii-folded, single-spaced. A key
    with a capital or a stray double space can never be hit.
    """
    from banner_api import normalize_instructor_key
    for k, v in BANNER_ALIASES.items():
        assert k == normalize_instructor_key(k), f"key not normalized: {k!r}"
        assert v == normalize_instructor_key(v), f"value not normalized: {v!r}"


def test_banner_aliases_never_map_a_name_to_itself():
    same = sorted(k for k, v in BANNER_ALIASES.items() if k == v)
    assert same == [], f"no-op entries: {same}"


def test_ambiguous_match_is_refused(cur):
    cur.execute("INSERT INTO professors_catalog (slug, name, name_key) "
                "VALUES ('annie-witte-2', 'Annie Witte', 'annie witte')")
    slug, _, method, candidates = match_one("annie witte", catalog_index(cur))
    assert (slug, method) == (None, "ambiguous")
    assert sorted(candidates) == ["annie-witte", "annie-witte-2"]


def test_ambiguous_alias_match_reports_the_candidates_it_actually_saw(cur):
    """The bug this guards against: an ambiguity found via ALIAS_MAP lives at
    the aliased key ("benjamin tasker"), not at instructor_key itself
    ("ben tasker") — a caller that re-reads index.get(instructor_key) to
    rebuild the candidate list finds nothing there, so
    banner_unmatched.candidates comes back empty even though match_one saw
    two hits. match_one must hand back the candidates it actually rejected.
    """
    cur.execute("INSERT INTO professors_catalog (slug, name, name_key) VALUES "
                "('benjamin-tasker', 'Benjamin Tasker', 'benjamin tasker'), "
                "('benjamin-tasker-2', 'Benjamin Tasker', 'benjamin tasker')")
    slug, _, method, candidates = match_one("ben tasker", catalog_index(cur))
    assert (slug, method) == (None, "ambiguous")
    assert sorted(candidates) == ["benjamin-tasker", "benjamin-tasker-2"]
    # index.get(instructor_key) — the pre-fix source of candidates — is empty
    # for this instructor_key, proving the old approach would have produced [].
    assert catalog_index(cur).get("ben tasker") is None


def test_group_dedupes_courses_and_collects_campuses():
    groups = group_instructors([
        brow(course="ACCT1201", campus="Boston"),
        brow(course="ACCT1201", campus="Boston"),   # another section, same course
        brow(course="CS3000", campus="Oakland, CA"),
    ])
    g = groups["annie witte"]
    assert g["course_codes"] == ["ACCT1201", "CS3000"]
    assert g["campuses"] == ["Boston", "Oakland, CA"]


def test_group_drops_non_place_campuses():
    """Banner puts "No campus, no room needed" in campusDescription — 207 teaching
    rows on the real Fall 2026 load. It must never reach the chip as "· No campus,
    no room needed". "Online" is a real answer for a student and stays."""
    groups = group_instructors([
        brow(course="CS3000", campus="No campus, no room needed"),
        brow(course="CS4400", campus="Online"),
    ])
    assert groups["annie witte"]["campuses"] == ["Online"]
    assert groups["annie witte"]["course_codes"] == ["CS3000", "CS4400"]


def test_group_excludes_individual_instruction():
    """Thesis supervision is not a class a student registers for."""
    groups = group_instructors([
        brow(course="CS7999", schedule="Individual Instruction"),
        brow(course="CS3000"),
    ])
    assert groups["annie witte"]["course_codes"] == ["CS3000"]


def test_group_drops_instructor_with_only_non_teaching_sections():
    groups = group_instructors([brow(course="CS7999", schedule="Individual Instruction")])
    assert groups == {}


def test_group_drops_instructor_with_no_courses_recorded():
    """A row can survive the schedule_type filter yet carry no subject_course
    (e.g. a malformed Banner record). Confirm the empty-courses guard, not just
    the schedule_type filter above it, keeps such an instructor out of the
    result — otherwise a chip could render with no course to show."""
    groups = group_instructors([brow(course="", schedule="Lecture")])
    assert groups == {}


def test_group_collects_every_term_code():
    """Law and CPS siblings must merge into one season entry."""
    groups = group_instructors([brow(term="202710"), brow(term="202715", course="LAW1000")])
    assert groups["annie witte"]["term_codes"] == ["202710", "202715"]


def test_build_rows_produces_teaching_row(cur):
    groups = group_instructors([brow(course="CS3000"), brow(course="ACCT1201")])
    teaching, unmatched = build_rows(groups, catalog_index(cur), "Fall 2026", SCRAPED)
    assert unmatched == []
    slug, name_key, term_desc, term_codes, courses, campuses, method, ts = teaching[0]
    assert (slug, name_key, term_desc) == ("annie-witte", "annie witte", "Fall 2026")
    assert courses == "ACCT1201,CS3000"      # sorted, deduped
    assert term_codes == "202710"
    assert campuses == "Boston"
    assert method == "name_key"
    assert ts == SCRAPED


def test_build_rows_joins_campuses_with_pipe(cur):
    """Campus names contain commas ("Oakland, CA"), so the stored form cannot be
    comma-separated — the API splits this column and would render "Canada" as its
    own campus. Course codes stay comma-joined; they never contain commas.
    """
    groups = group_instructors([
        brow(course="CS6620", campus="Online"),
        brow(course="CS6620", campus="Vancouver, Canada"),
    ])
    teaching, _ = build_rows(groups, catalog_index(cur), "Fall 2026", SCRAPED)
    campuses = teaching[0][5]
    assert campuses == "Online|Vancouver, Canada"
    assert campuses.split("|") == ["Online", "Vancouver, Canada"]


def test_build_rows_records_unmatched(cur):
    groups = group_instructors([brow(key="brand new", name="New, Brand")])
    teaching, unmatched = build_rows(groups, catalog_index(cur), "Fall 2026", SCRAPED)
    assert teaching == []
    assert unmatched[0][1] == "brand new"
    assert unmatched[0][4] == "no_match"


def test_build_rows_records_ambiguous_with_candidates(cur):
    cur.execute("INSERT INTO professors_catalog (slug, name, name_key) "
                "VALUES ('annie-witte-2', 'Annie Witte', 'annie witte')")
    groups = group_instructors([brow()])
    teaching, unmatched = build_rows(groups, catalog_index(cur), "Fall 2026", SCRAPED)
    assert teaching == []
    assert unmatched[0][4] == "ambiguous"
    assert "annie-witte" in unmatched[0][5] and "annie-witte-2" in unmatched[0][5]


def test_build_rows_merges_two_banner_keys_that_alias_to_one_catalog_row(cur):
    """FIX 5: "ben tasker" and "benjamin tasker" both resolve to the single
    catalog row "benjamin tasker" (one is an exact name_key hit, the other an
    ALIAS_MAP hit). Two separate output tuples would share the same
    (name_key, term_desc) primary key — under execute_values + ON CONFLICT DO
    UPDATE that's "cannot affect row a second time" and the whole matcher run
    dies. There must be exactly one output row, and it must carry the union
    of both instructors' course codes, campuses, and term codes — not just
    the first group's. The two groups are given different campuses and
    different term codes precisely so a merge that silently drops the later
    group's values (keeping only the first group's) fails this test instead
    of passing it by accident.
    """
    cur.execute("INSERT INTO professors_catalog (slug, name, name_key) "
                "VALUES ('benjamin-tasker', 'Benjamin Tasker', 'benjamin tasker')")
    groups = group_instructors([
        brow(key="ben tasker", name="Tasker, Ben", course="CS3000",
             campus="Boston", term="202710"),
        brow(key="benjamin tasker", name="Tasker, Benjamin", course="CS4000",
             campus="Oakland, CA", term="202715"),
    ])
    teaching, unmatched = build_rows(groups, catalog_index(cur), "Fall 2026", SCRAPED)
    assert unmatched == []
    assert len(teaching) == 1
    slug, name_key, term_desc, term_codes, courses, campuses, method, ts = teaching[0]
    assert (slug, name_key) == ("benjamin-tasker", "benjamin tasker")
    assert courses == "CS3000,CS4000"
    assert campuses == "Boston|Oakland, CA"
    assert term_codes == "202710,202715"


def test_build_rows_records_alias_path_ambiguity_candidates(cur):
    """FIX 8: the ambiguity here can only be found via ALIAS_MAP ("ben tasker"
    -> "benjamin tasker"). If build_rows rebuilt candidates by re-reading
    index.get(instructor_key) ("ben tasker") instead of using what match_one
    actually returned, this would come back empty — banner_unmatched exists
    to keep ambiguity reviewable, and an empty candidates column defeats that.
    """
    cur.execute("INSERT INTO professors_catalog (slug, name, name_key) VALUES "
                "('benjamin-tasker', 'Benjamin Tasker', 'benjamin tasker'), "
                "('benjamin-tasker-2', 'Benjamin Tasker', 'benjamin tasker')")
    groups = group_instructors([brow(key="ben tasker", name="Tasker, Ben")])
    teaching, unmatched = build_rows(groups, catalog_index(cur), "Fall 2026", SCRAPED)
    assert teaching == []
    assert unmatched[0][4] == "ambiguous"
    assert "benjamin-tasker" in unmatched[0][5] and "benjamin-tasker-2" in unmatched[0][5]


# ── single_term_desc ─────────────────────────────────────────────────────
# rows[0]["term_desc"] alone reads from an unordered SELECT; if
# banner_sections ever holds two seasons at once, whichever row happened to
# come back first would silently decide the label for every professor's chip.

def test_single_term_desc_returns_the_shared_value():
    rows = [{"term_desc": "Fall 2026"}, {"term_desc": "Fall 2026"}]
    assert single_term_desc(rows) == "Fall 2026"


def test_single_term_desc_raises_on_more_than_one_value():
    rows = [{"term_desc": "Fall 2026"}, {"term_desc": "Spring 2026"}]
    with pytest.raises(ValueError, match="2 distinct term_desc"):
        single_term_desc(rows)


# ── write_results ─────────────────────────────────────────────────────────
# professor_teaching/banner_unmatched are upserted, never inserted fresh, so a
# professor who drops off the current roster keeps their old row (and public
# chip) unless this run's rows for the current term_desc are cleared first.

def test_write_results_drops_professor_who_stopped_teaching_this_season(store_cur):
    """Annie had a row for Fall 2026 last run. This run she has no section at
    all (cancelled, reassigned, whatever) — teaching=[] for this run. Her old
    row must not survive: it is the public chip, and it would otherwise sit
    there, untouched, until the 21-day staleness guard expires it."""
    store_cur.execute(
        "INSERT INTO professor_teaching (professor_slug, name_key, term_desc, "
        "term_codes, course_codes, campuses, match_method, scraped_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", teaching_row())
    write_results(store_cur, "Fall 2026", teaching=[], unmatched=[])
    remaining = store_cur.execute("SELECT count(*) FROM professor_teaching").fetchone()[0]
    assert remaining == 0


def test_write_results_replaces_stale_course_list_for_the_same_professor(store_cur):
    """Annie taught CS1000 last run, CS2000 this run (reassigned sections).
    The upsert-only path can't be trusted to fully overwrite; confirm the old
    course list is actually gone, not merged or left alongside the new one."""
    store_cur.execute(
        "INSERT INTO professor_teaching (professor_slug, name_key, term_desc, "
        "term_codes, course_codes, campuses, match_method, scraped_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", teaching_row(courses="CS1000"))
    write_results(store_cur, "Fall 2026",
                  teaching=[teaching_row(courses="CS2000", scraped_at="new")],
                  unmatched=[])
    rows = store_cur.execute(
        "SELECT course_codes FROM professor_teaching WHERE name_key = 'annie witte'"
    ).fetchall()
    assert [r[0] for r in rows] == ["CS2000"]


def test_write_results_drops_unmatched_instructor_who_now_matches(store_cur):
    """Symmetric case for banner_unmatched: an instructor unmatched last run
    (e.g. a catalog rename) who now matches must not still show up as
    unmatched, and an instructor who never matches but stops appearing this
    run must be dropped from the review queue too."""
    store_cur.execute(
        "INSERT INTO banner_unmatched (term_desc, instructor_key, instructor_name, "
        "course_codes, reason, candidates, scraped_at) "
        "VALUES ('Fall 2026', 'brand new', 'New, Brand', 'CS1000', "
        "'no_match', '', 'old')")
    write_results(store_cur, "Fall 2026", teaching=[], unmatched=[])
    remaining = store_cur.execute("SELECT count(*) FROM banner_unmatched").fetchone()[0]
    assert remaining == 0


def test_write_results_keeps_current_season_rows_that_are_still_present(store_cur):
    """The fix must not become a delete-everything bug: a professor still
    teaching this season, reinserted with the same data, must still be there
    afterwards."""
    write_results(store_cur, "Fall 2026", teaching=[teaching_row()], unmatched=[])
    remaining = store_cur.execute("SELECT count(*) FROM professor_teaching").fetchone()[0]
    assert remaining == 1


# ── check_match_gate ────────────────────────────────────────────────────────
# The same-season DELETE in write_results is correct, but nothing upstream of
# it stopped a collapsed run (e.g. professors_catalog empty mid-rebuild)
# from deleting every current-season row and inserting nothing. check_match_gate
# is the thing that now stops write_results from ever being reached on a run
# like that.

def test_check_match_gate_raises_when_teaching_is_empty_but_groups_is_not():
    """groups non-empty (Banner clearly has data), teaching empty (nothing
    matched at all) — the signature of an empty catalog index."""
    groups = {f"person {i}": object() for i in range(10)}
    with pytest.raises(MatchGateFailed, match="matched 0 of 10"):
        check_match_gate(groups, teaching=[], dry_run=False)


def test_check_match_gate_allows_a_low_share_of_banner_instructors():
    """The catalog only holds professors with an RMP page, so most Banner
    instructors legitimately match nothing: measured 36% on Fall 2026
    (2026-10-02). A low share of Banner is normal, not a broken run."""
    groups = {f"person {i}": object() for i in range(100)}
    teaching = [object()] * 36
    check_match_gate(groups, teaching, previous=None, dry_run=False)   # must not raise


def test_check_match_gate_raises_on_a_sharp_drop_from_the_previous_run():
    """A catalog rebuilt mid-run or a name_key normalization change shows up
    as far fewer matches than last time, whatever share of Banner that is."""
    groups = {f"person {i}": object() for i in range(100)}
    with pytest.raises(MatchGateFailed, match="previous run matched 30"):
        check_match_gate(groups, [object()] * 14, previous=30, dry_run=False)


def test_check_match_gate_allows_a_normal_change_from_the_previous_run():
    groups = {f"person {i}": object() for i in range(100)}
    check_match_gate(groups, [object()] * 27, previous=30, dry_run=False)   # must not raise


def test_check_match_gate_at_exactly_the_ratio_does_not_raise():
    """Strict `<`, the convention banner_scrape.py's MIN_SECTION_RATIO and
    MIN_ROSTER_RATIO use: landing exactly on the ratio is not the failure."""
    groups = {f"person {i}": object() for i in range(100)}
    teaching = [object()] * 15
    assert len(teaching) / 30 == MIN_KEPT_RATIO
    check_match_gate(groups, teaching, previous=30, dry_run=False)   # must not raise


def test_check_match_gate_skips_when_groups_is_empty():
    """groups empty is "Banner legitimately has almost nobody" — owned by the
    banner_sections-is-empty check earlier in main(), not this gate."""
    check_match_gate({}, teaching=[], dry_run=False)   # must not raise


def test_check_match_gate_dry_run_never_raises_even_on_a_collapsed_run():
    """--dry-run must still report the numbers so an operator can diagnose a
    bad run; it must never be the thing that dies before the report prints."""
    groups = {f"person {i}": object() for i in range(10)}
    check_match_gate(groups, teaching=[], dry_run=True)   # must not raise


def test_collapsed_run_gate_raises_and_leaves_existing_rows_intact(cur, store_cur):
    """The scenario FIX 1 exists for: a same-season run where the catalog
    index came back empty (e.g. professors_catalog mid-rebuild by backend/pipeline).
    groups is non-empty — Banner had real sections — but the empty index
    means build_rows matches nobody. The gate must raise before write_results
    is ever called, so the professor's existing row from a prior good run
    survives untouched.
    """
    store_cur.execute(
        "INSERT INTO professor_teaching (professor_slug, name_key, term_desc, "
        "term_codes, course_codes, campuses, match_method, scraped_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", teaching_row())
    groups = group_instructors([brow(key="annie witte"),
                                brow(key="patrick hurley", course="CS2000")])
    teaching, unmatched = build_rows(groups, {}, "Fall 2026", SCRAPED)
    assert teaching == []   # sanity: this really is a total collapse

    with pytest.raises(MatchGateFailed):
        check_match_gate(groups, teaching, dry_run=False)
        write_results(store_cur, "Fall 2026", teaching, unmatched)   # unreached

    remaining = store_cur.execute(
        "SELECT count(*) FROM professor_teaching").fetchone()[0]
    assert remaining == 1


def test_healthy_run_passes_gate_and_writes_normally(cur, store_cur):
    """Symmetric case: a real, non-collapsed run must pass the gate and write
    exactly as before FIX 1."""
    groups = group_instructors([brow(key="annie witte"),
                                brow(key="patrick hurley", course="CS2000")])
    teaching, unmatched = build_rows(groups, catalog_index(cur), "Fall 2026", SCRAPED)
    assert len(teaching) == 2   # sanity: both match the catalog fixture

    check_match_gate(groups, teaching, dry_run=False)   # must not raise
    write_results(store_cur, "Fall 2026", teaching, unmatched)
    remaining = store_cur.execute(
        "SELECT count(*) FROM professor_teaching").fetchone()[0]
    assert remaining == 2


# ── current season, history tables, and the read path ────────────────────

from banner_history import (build_course_instructors,  # noqa: E402
                            build_course_offerings)
from load_banner_to_crdb import apply_ddl, write_term  # noqa: E402
from match_banner_instructors import (HISTORY_DDL, chip_rows,  # noqa: E402
                                      current_season, read_banner,
                                      write_history)


def term(code, label, group, view_only):
    return {"term_code": code, "term_label": label, "season_group": group,
            "view_only": view_only}


def test_current_season_is_the_earliest_open_fall_or_spring_with_its_siblings():
    rows = [term("202710", "Fall 2026", "Fall", False),
            term("202715", "Fall 2026", "Fall", False),
            term("202730", "Spring 2027", "Spring", False),
            term("202650", "Summer Full 2026", "Summer", False),
            term("202630", "Spring 2026", "Spring", True)]
    assert current_season(rows) == ("Fall 2026", ["202710", "202715"])


def test_current_season_raises_when_nothing_is_open():
    with pytest.raises(ValueError):
        current_season([term("202630", "Spring 2026", "Spring", True)])


@pytest.fixture
def banner_db():
    """The loader's three tables plus the matcher's, with two real terms."""
    conn = sqlite3.connect(":memory:")
    c = conn.cursor()
    apply_ddl(c)
    for ddl in (TEACHING_DDL, UNMATCHED_DDL, HISTORY_DDL):
        for stmt in ddl.split(";"):
            if stmt.strip():
                c.execute(stmt.replace("TIMESTAMPTZ", "TIMESTAMP"))

    def sec(crn, course, enrollment):
        return {"crn": crn, "subject": course[:-4], "subject_course": course,
                "schedule_type": "Lecture", "campus": "Boston",
                "instructional_method": "Traditional", "course_title": course,
                "enrollment": enrollment, "max_enrollment": 40,
                "credit_hours_low": 4.0}

    def ins(term_code, crn, key):
        return {"term_code": term_code, "crn": crn, "instructor_key": key,
                "instructor_name": key.title(), "is_primary": True}

    stats = {"section_count": 2, "attributed_sections": 1, "instructor_count": 1}
    write_term(c, "202630", {"label": "Spring 2026", "season": "Spring",
                             "season_group": "Spring", "year": 2026,
                             "track": "Semester", "view_only": True}, None,
               {"sections": [sec("1", "CS3500", 35), sec("2", "CS3500", 25)],
                "instructors": [ins("202630", "1", "annie witte")], "stats": stats})
    write_term(c, "202710", {"label": "Fall 2026", "season": "Fall",
                             "season_group": "Fall", "year": 2026,
                             "track": "Semester", "view_only": False}, None,
               {"sections": [sec("9", "CS4500", 10), sec("8", "CS4500", 0)],
                "instructors": [ins("202710", "9", "patrick hurley")], "stats": stats})
    return c


def test_read_banner_joins_terms_onto_sections_and_instructors(banner_db):
    terms, sections, instructors = read_banner(banner_db)
    assert len(terms) == 2 and len(sections) == 4 and len(instructors) == 2
    s = next(s for s in sections if s["crn"] == "1")
    assert (s["term_label"], s["season_group"], s["closed"]) == ("Spring 2026", "Spring", True)
    i = next(i for i in instructors if i["crn"] == "9")
    assert (i["subject_course"], i["closed"]) == ("CS4500", False)


def test_chip_rows_take_only_the_current_season(banner_db):
    terms, _, instructors = read_banner(banner_db)
    label, codes = current_season(terms)
    rows = chip_rows(instructors, label, codes)
    assert [(r["instructor_key"], r["term_desc"]) for r in rows] == [
        ("patrick hurley", "Fall 2026")]
    assert list(group_instructors(rows)) == ["patrick hurley"]


def test_history_round_trip_and_rebuild_replaces_everything(banner_db, cur):
    _, sections, instructors = read_banner(banner_db)
    index = catalog_index(cur)

    def match(key):
        slug, name_key, method, _ = match_one(key, index)
        return slug, name_key, method

    pairs = build_course_instructors(instructors, match)
    offerings = build_course_offerings(sections, instructors)
    assert write_history(banner_db, pairs, offerings) == (2, 2)
    got = dict(banner_db.execute(
        "SELECT subject_course, avg_section_size FROM banner_course_offerings").fetchall())
    assert got == {"CS3500": 30.0, "CS4500": None}     # CS4500 only has an open term
    slugs = {r[0] for r in banner_db.execute(
        "SELECT professor_slug FROM banner_course_instructors")}
    assert slugs == {"annie-witte", "patrick-hurley"}

    write_history(banner_db, pairs[:1], offerings[:1])
    assert banner_db.execute("SELECT count(*) FROM banner_course_offerings").fetchone()[0] == 1
    assert banner_db.execute("SELECT count(*) FROM banner_course_instructors").fetchone()[0] == 1


from match_banner_instructors import approved_renames  # noqa: E402


def test_approved_renames_keep_only_pairs_whose_codes_exist():
    offs = [{"subject_course": c} for c in ("ECON1291", "ECON3291", "AFAM1225", "AFCS1225", "AFAM2000")]
    got = approved_renames(offs, {"ECON1291": "ECON3291", "OLD1000": "NEW1000"}, {"AFAM": "AFCS"})
    assert got == [{"old_code": "AFAM1225", "new_code": "AFCS1225"},
                   {"old_code": "ECON1291", "new_code": "ECON3291"}]
