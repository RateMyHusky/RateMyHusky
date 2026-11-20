from profile_stats import format_report


def stats(**over):
    base = {"profiles": 5, "opted_out": 1, "answered": 4, "by_grad_year": {"2028": 2, "grad student": 1},
            "by_major": {"Biology, BS": 1, "Computer Science, BS": 3},
            "views": 8, "view_students": 4, "view_professors": 3, "view_courses": 2,
            "views_per_student": 2.0, "since": "2026-11-20",
            "ratings_undergrad": 6, "ratings_grad": 2, "ratings_unknown": 9,
            "ratings_by_grad_year": {"2027": 2, "2028": 4}}
    base.update(over)
    return base


def test_report_prints_each_number_with_its_label():
    out = format_report(stats())
    for line in ["profile rows (incl. opted out): 5", "answered profiles: 4", "opted out: 1", "2028: 2", "grad student: 1", "page views: 8",
                 "distinct students: 4", "distinct professors: 3", "distinct courses: 2",
                 "views per student: 2.0", "all submitted ratings (any status) since 2026-11-20", "undergrad: 6",
                 "grad student: 2", "unknown (no profile or opted out): 9", "2027: 2", "2028: 4"]:
        assert line in out


def test_report_lists_majors_by_count_descending():
    out = format_report(stats())
    assert out.index("Computer Science, BS: 3") < out.index("Biology, BS: 1")


def test_report_handles_empty_tables():
    out = format_report(stats(profiles=0, opted_out=0, answered=0, by_grad_year={}, by_major={}, views=0,
                              view_students=0, view_professors=0, view_courses=0,
                              views_per_student=0, since=None,
                              ratings_undergrad=0, ratings_grad=0, ratings_unknown=0, ratings_by_grad_year={}))
    assert "views per student: 0" in out
