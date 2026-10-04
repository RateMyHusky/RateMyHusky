from pipeline.course_codes import normalize_code, plan_codes

VALID = {"CS2500", "CS3500", "ENGW1111"}


def test_messy_inputs():
    assert normalize_code("cs 2500", VALID) == "CS2500"
    assert normalize_code("CS2500 ", VALID) == "CS2500"
    assert normalize_code("CS-2500", VALID) == "CS2500"
    assert normalize_code("FUNDIES", VALID) is None
    assert normalize_code("", VALID) is None
    assert normalize_code(None, VALID) is None


def test_codes_outside_the_catalog_are_null():
    assert normalize_code("CS9999", VALID) is None


def test_plan_covers_every_review():
    reviews = [{"id": 1, "course": "cs2500"}, {"id": 2, "course": "FUNDIES"}]
    assert plan_codes(reviews, VALID) == [(1, "CS2500"), (2, None)]
