from profile_stats import format_report


def stats(**over):
    base = {"profiles": 5, "opted_out": 1, "by_grad_year": {"2028": 2, "grad student": 1},
            "by_major": {"Biology, BS": 1, "Computer Science, BS": 3},
            "views": 8, "view_students": 4, "view_professors": 3, "view_courses": 2,
            "views_per_student": 2.0, "since": "2026-11-20",
            "ratings_with_year": 6, "ratings_without_year": 9}
    base.update(over)
    return base


def test_report_prints_each_number_with_its_label():
    out = format_report(stats())
    for line in ["profiles: 5", "opted out: 1", "2028: 2", "grad student: 1", "page views: 8",
                 "distinct students: 4", "distinct professors: 3", "distinct courses: 2",
                 "views per student: 2.0", "ratings since 2026-11-20", "with grad year: 6",
                 "without grad year: 9"]:
        assert line in out


def test_report_lists_majors_by_count_descending():
    out = format_report(stats())
    assert out.index("Computer Science, BS: 3") < out.index("Biology, BS: 1")


def test_report_handles_empty_tables():
    out = format_report(stats(profiles=0, opted_out=0, by_grad_year={}, by_major={}, views=0,
                              view_students=0, view_professors=0, view_courses=0,
                              views_per_student=0, since=None,
                              ratings_with_year=0, ratings_without_year=0))
    assert "views per student: 0" in out
