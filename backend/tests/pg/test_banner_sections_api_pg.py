
"""Test the Banner section lookup API against PostgreSQL."""

from tests.pg.pgutil import truncate


def test_banner_section_lookup_pg(pg, live_server):
    truncate(
        pg,
        "banner_terms",
        "banner_sections",
        "banner_section_instructors",
        "banner_course_instructors",
        "banner_roster_duplicates",
        "professors_catalog",
    )

    with pg.cursor() as cur:
        cur.execute("""
            INSERT INTO banner_sections
                (term_code, crn, subject_course)
            VALUES
                ('202730', '36973', 'CS2500'),
                ('202730', '31896', 'CS2500')
        """)

        cur.execute("""
            INSERT INTO banner_section_instructors
                (term_code, crn, instructor_key,
                 instructor_name, is_primary)
            VALUES
                ('202730', '36973', 'rachlin john',
                 'Rachlin, John', TRUE),
                ('202730', '31896', 'van julie',
                 'Van, Julie', TRUE)
        """)

        cur.execute("""
            INSERT INTO banner_course_instructors
                (subject_course, instructor_key,
                 professor_slug, match_method,
                 terms_taught, sections,
                 first_term_code, last_term_code,
                 last_term_label)
            VALUES
                ('CS2500', 'rachlin john',
                 'john-rachlin', 'exact',
                 1, 1, '202730', '202730',
                 'Spring 2027')
        """)

        cur.execute("""
            INSERT INTO professors_catalog
                (slug, name, name_key,
                 avg_rating, num_ratings)
            VALUES
                ('john-rachlin', 'John Rachlin',
                 'john rachlin', 4.63, 52)
        """)

    pg.commit()

    response = live_server.app.test_client().post(
        "/api/banner/sections",
        json={"term": "202730", "crns": ["36973", "31896"]},
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["36973"] == {
        "instructor": "Rachlin, John",
        "slug": "john-rachlin",
        "rating": 4.63,
        "numRatings": 52,
    }

    assert data["31896"] == {
        "instructor": "Van, Julie",
        "slug": None,
        "rating": None,
        "numRatings": 0,
    }


def test_banner_section_edge_cases_pg(pg, live_server):
    truncate(
        pg,
        "banner_terms",
        "banner_sections",
        "banner_section_instructors",
        "banner_course_instructors",
        "banner_roster_duplicates",
        "professors_catalog",
    )

    with pg.cursor() as cur:
        # four sections: alias, ambiguous, multiple, and unique primary
        cur.execute("""
            INSERT INTO banner_sections
                (term_code, crn, subject_course)
            VALUES
                ('202730', '10001', 'CS2500'),
                ('202730', '10002', 'CS2500'),
                ('202730', '10003', 'CS2500'),
                ('202730', '10004', 'CS2500')
        """)

        cur.execute("""
            INSERT INTO banner_section_instructors
                (term_code, crn, instructor_key,
                 instructor_name, is_primary)
            VALUES
                ('202730', '10001', 'johnny rachlin',
                 'Rachlin, Johnny', TRUE),
                ('202730', '10002', 'rachlin john',
                 'Rachlin, John', TRUE),
                ('202730', '10003', 'rachlin john',
                 'Rachlin, John', FALSE),
                ('202730', '10003', 'jane smith',
                 'Smith, Jane', FALSE),
                ('202730', '10004', 'rachlin john',
                 'Rachlin, John', TRUE),
                ('202730', '10004', 'jane smith',
                 'Smith, Jane', FALSE)
        """)

        # the matcher has already resolved this alias
        cur.execute("""
            INSERT INTO banner_course_instructors
                (subject_course, instructor_key,
                 instructor_keys, professor_slug,
                 match_method, terms_taught, sections,
                 first_term_code, last_term_code,
                 last_term_label)
            VALUES
                ('CS2500', 'rachlin john',
                 'rachlin john|johnny rachlin',
                 'john-rachlin', 'alias', 1, 1,
                 '202730', '202730', 'Spring 2027'),
                ('CS2500', 'jane smith',
                 'jane smith',
                 'jane-smith', 'exact', 1, 1,
                 '202730', '202730', 'Spring 2027')
        """)

        cur.execute("""
            INSERT INTO professors_catalog
                (slug, name, name_key, avg_rating, num_ratings)
            VALUES
                ('john-rachlin', 'John Rachlin',
                 'john rachlin', 4.63, 52),
                ('jane-smith', 'Jane Smith',
                 'jane smith', 4.20, 30)
        """)

        # mark one term-level identity as ambiguous
        cur.execute("""
            INSERT INTO banner_roster_duplicates
                (term_code, instructor_key)
            VALUES ('202730', 'rachlin john')
        """)

    pg.commit()

    client = live_server.app.test_client()

    response = client.post(
        "/api/banner/sections",
        json={"term": "202730", "crns": ["10001", "10002", "10003", "10004", "99999"]},
    )

    assert response.status_code == 200
    data = response.get_json()

    # alias has a verified mapping and returns its rating
    assert data["10001"]["slug"] == "john-rachlin"
    assert data["10001"]["rating"] == 4.63
    assert data["10001"]["numRatings"] == 52

    # duplicated identity must not publish a rating
    assert data["10002"]["instructor"] == "Rachlin, John"
    assert data["10002"]["slug"] is None
    assert data["10002"]["rating"] is None

    # two instructors without a unique primary: abstain
    assert data["10003"]["slug"] is None
    assert data["10003"]["rating"] is None

    # even a primary instructor must respect the ambiguity flag
    assert data["10004"]["slug"] is None
    assert data["10004"]["rating"] is None

    # missing CRNs must not invent results
    assert "99999" not in data
