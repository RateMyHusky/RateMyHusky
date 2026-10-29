"""The weekly rebuild against real PostgreSQL: run twice, no schema drift."""

import copy

import pytest

from pipeline import banner_roster, course_codes, name_keys, read_models
from tests.pg.pgutil import rows, scalar, schema_snapshot, truncate
from tests.pg.seed import CATALOG, COUNTS, COURSES, SUMMARIES

READ_MODELS = ("professors_catalog", "course_catalog", "source_summary", "stats_cache")


def test_rebuild_twice_bumps_data_version_without_schema_drift(pg):
    truncate(pg, *READ_MODELS)
    before = schema_snapshot(pg)

    read_models.write(pg, CATALOG, COURSES, SUMMARIES, COUNTS)
    assert scalar(pg, "SELECT value FROM stats_cache WHERE key = 'data_version'") == 1

    second = CATALOG + [dict(CATALOG[0], slug="bob-jones", name="Bob Jones", name_key="bob jones")]
    read_models.write(pg, second, COURSES, SUMMARIES, dict(COUNTS, professors=2))
    assert scalar(pg, "SELECT value FROM stats_cache WHERE key = 'data_version'") == 2
    assert scalar(pg, "SELECT count(*) FROM professors_catalog") == 2
    assert scalar(pg, "SELECT value FROM stats_cache WHERE key = 'professors'") == 2
    assert scalar(pg, "SELECT count(*) FROM source_summary") == len(SUMMARIES)
    dist = rows(pg, "SELECT rating_distribution FROM source_summary WHERE professor_slug = 'alice-smith'")
    assert dist[0]["rating_distribution"] == {"5": 3}

    assert schema_snapshot(pg) == before


def test_failed_rebuild_leaves_the_previous_data(pg):
    truncate(pg, *READ_MODELS)
    read_models.write(pg, CATALOG, COURSES, SUMMARIES, COUNTS)

    bad = copy.deepcopy(SUMMARIES)
    bad[0]["source"] = None            # NOT NULL: fails on the third table
    other = [dict(CATALOG[0], slug="carol-new", name="Carol New", name_key="carol new")]
    with pytest.raises(Exception):
        read_models.write(pg, other, [], bad, COUNTS)

    assert [r["slug"] for r in rows(pg, "SELECT slug FROM professors_catalog")] == ["alice-smith"]
    assert scalar(pg, "SELECT count(*) FROM course_catalog") == 1
    assert scalar(pg, "SELECT value FROM stats_cache WHERE key = 'data_version'") == 1


def test_course_codes_and_name_keys_apply_through_temp_tables(pg):
    truncate(pg, "rmp_reviews")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO rmp_reviews (id, professor_name, course) "
                    "VALUES (10, 'Alice Smith', 'cs 2500'), (11, 'Alice Smith', 'nope')")
    pg.commit()

    assert course_codes.apply_codes(pg, [(10, "CS2500"), (11, None)]) == 1
    assert name_keys.apply_name_keys(pg, [(10, "alice smith"), (11, "alice smith")]) == 2
    # Twice in one session: each call drops its temp table before committing.
    assert course_codes.apply_codes(pg, [(10, "CS2500")]) == 0

    got = {r["id"]: (r["course_code"], r["name_key"]) for r in rows(
        pg, "SELECT id, course_code, name_key FROM rmp_reviews")}
    assert got == {10: ("CS2500", "alice smith"), 11: (None, "alice smith")}


def test_apply_banner_professors_writes_origin_and_skips_taken_slugs(pg):
    truncate(pg, "professors", "banner_course_instructors")
    with pg.cursor() as cur:
        cur.execute("INSERT INTO professors (slug, name, name_key) "
                    "VALUES ('lucia-nunez', 'Lucia Nunez', 'lucia nunez')")
        for key in ("wei wang", "lucia nunez"):
            cur.execute("INSERT INTO banner_course_instructors (subject_course, instructor_key, "
                        "match_method, terms_taught, sections, first_term_code, last_term_code, "
                        "last_term_label) VALUES ('CS2500', %s, 'no_match', 1, 1, '202610', "
                        "'202610', 'Fall 2025')", (key,))
    pg.commit()

    def banner(slug, name):
        return {"slug": slug, "name": name, "name_key": name.lower(), "department": None,
                "college": "Other", "image_url": None, "focus_x": None, "focus_y": None,
                "origin": "banner"}

    banner_roster.apply_banner_professors(
        pg, [banner("lucia-nunez", "Lucia Nunez"), banner("wei-wang", "Wei Wang")])

    assert [
        (r["slug"], r["origin"])
        for r in rows(pg, "SELECT slug, origin FROM professors ORDER BY slug")
    ] == [("lucia-nunez", "rmp"), ("wei-wang", "banner")]
    # Only the inserted professor's rows are linked; the taken slug's are left to the matcher.
    assert [
        (r["instructor_key"], r["professor_slug"], r["name_key"], r["match_method"])
        for r in rows(pg, "SELECT instructor_key, professor_slug, name_key, match_method "
                          "FROM banner_course_instructors ORDER BY instructor_key")
    ] == [("lucia nunez", None, None, "no_match"), ("wei wang", "wei-wang", "wei wang", "name_key")]
