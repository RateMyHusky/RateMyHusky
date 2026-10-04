from pipeline.blend import blend


def row(source, rating, n, slug="olin-guha", code="", **over):
    base = {"professor_slug": slug, "course_code": code, "source": source, "rating": rating,
            "difficulty": 3.0, "would_take_again_pct": 80.0, "num_ratings": n, "num_comments": n,
            "hours_per_week": None, "rating_distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": n},
            "grade_distribution": {"A": n}}
    base.update(over)
    return base


def test_one_source_blend_equals_the_source():
    src = row("rmp", 4.25, 12)
    [b] = blend([src])
    assert b["source"] == "blend"
    for k in ("rating", "difficulty", "would_take_again_pct", "num_ratings", "num_comments",
              "hours_per_week", "rating_distribution", "grade_distribution"):
        assert b[k] == src[k], k


def test_two_sources_are_rating_count_weighted():
    [b] = blend([row("rmp", 4.0, 30), row("survey", 2.0, 10, hours_per_week=6.0)])
    assert b["rating"] == 3.5                  # (4*30 + 2*10) / 40
    assert b["num_ratings"] == 40 and b["num_comments"] == 40
    assert b["hours_per_week"] == 6.0          # only one source reports it
    assert b["rating_distribution"]["5"] == 40 and b["grade_distribution"] == {"A": 40}


def test_value_with_zero_weight_still_blends():
    # An RMP page rating with no stored reviews: num_ratings 0 but a real rating.
    [b] = blend([row("rmp", 4.0, 0)])
    assert b["rating"] == 4.0


def test_one_blend_row_per_entity():
    out = blend([row("rmp", 4.0, 1), row("rmp", 3.0, 1, code="CS3500"), row("rmp", 5.0, 1, slug="", code="CS3500")])
    assert sorted((r["professor_slug"], r["course_code"]) for r in out) == [
        ("", "CS3500"), ("olin-guha", ""), ("olin-guha", "CS3500")]
