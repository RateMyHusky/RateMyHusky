from pipeline.seed import plan_seed

URL = "https://www.ratemyprofessors.com/professor/{}"


def page(name, pid, dept="Computer Science"):
    return {"name": name, "department": dept, "professor_url": URL.format(pid) if pid else None}


def cat(slug, name_key, name=None):
    return {"slug": slug, "name": name or name_key.title(), "name_key": name_key,
            "department": "Computer Science", "college": "Khoury", "image_url": None,
            "focus_x": None, "focus_y": None, "professor_url": URL.format(1)}


def test_seed_links_through_the_alias_resolver():
    # prof_aliases maps the RMP spelling "laney strange" to "elena strange".
    links, profs, counts, _ = plan_seed([page("Laney Strange", 11)], [cat("elena-strange", "elena strange")],
                                        is_denied=lambda k: False)
    assert links == [{"rmp_id": 11, "rmp_name": "Laney Strange", "rmp_department": "Computer Science",
                      "professor_url": URL.format(11), "slug": "elena-strange", "match_method": "frozen"}]
    assert [p["slug"] for p in profs] == ["elena-strange"]


def test_seed_copies_professor_fields_verbatim():
    row = {**cat("olin-guha", "olin guha", name="Olin Guha"), "image_url": "https://img/o.jpg",
           "focus_x": 40.0, "focus_y": 20.0}
    _, profs, _, _ = plan_seed([page("Olin Guha", 1)], [row], is_denied=lambda k: False)
    assert profs == [{k: row[k] for k in ("slug", "name", "name_key", "department", "college",
                                          "image_url", "focus_x", "focus_y")}]


def test_seed_counts_unmatched_and_missing_urls():
    _, _, counts, detail = plan_seed([page("Nobody Here", 5), page("No Url", None)],
                                     [cat("olin-guha", "olin guha")], is_denied=lambda k: False)
    assert (counts["unmatched"], counts["no_rmp_id"], counts["links"]) == (1, 1, 0)
    assert ("Nobody Here", "unmatched") in detail


def test_seed_skips_duplicate_rmp_ids():
    links, _, counts, _ = plan_seed([page("Olin Guha", 1), page("Olin Guha", 1)],
                                    [cat("olin-guha", "olin guha")], is_denied=lambda k: False)
    assert len(links) == 1 and counts["duplicate_rmp_id"] == 1


def test_two_pages_one_professor():
    links, profs, _, _ = plan_seed([page("Olin Guha", 1), page("Olin Guha", 2, dept="Khoury")],
                                   [cat("olin-guha", "olin guha")], is_denied=lambda k: False)
    assert [l["rmp_id"] for l in links] == [1, 2] and len(profs) == 1


def test_seed_skips_denied_without_detail():
    _, _, counts, detail = plan_seed([page("Olin Guha", 1)], [cat("olin-guha", "olin guha")],
                                     is_denied=lambda k: k == "olin guha")
    assert counts["denied"] == 1 and counts["links"] == 0
    assert detail == []


def test_ambiguous_catalog_name_key_is_not_guessed():
    _, _, counts, _ = plan_seed([page("Olin Guha", 1)],
                                [cat("olin-guha", "olin guha"), cat("olin-guha-2", "olin guha")],
                                is_denied=lambda k: False)
    assert counts["ambiguous"] == 1 and counts["links"] == 0


def test_denied_page_without_rmp_id_counts_as_denied_not_detail():
    _, _, counts, detail = plan_seed([page("Olin Guha", None)], [cat("olin-guha", "olin guha")],
                                     is_denied=lambda k: k == "olin guha")
    assert counts["denied"] == 1 and counts["no_rmp_id"] == 0
    assert detail == []


def _same_id(first, second):
    # "Olin Old" is not in the catalog; "Olin Guha" is. Both pages carry RMP id 1.
    return plan_seed([page(first, 1), page(second, 1)], [cat("olin-guha", "olin guha")],
                     is_denied=lambda k: False)


def test_unmatched_then_matched_same_id_links_the_matched_page():
    links, _, counts, detail = _same_id("Olin Old", "Olin Guha")
    assert [l["slug"] for l in links] == ["olin-guha"]
    assert counts["unmatched"] == 1 and counts["duplicate_rmp_id"] == 0
    assert detail == [("Olin Old", "unmatched")]


def test_matched_then_unmatched_same_id_is_order_independent():
    links, _, counts, detail = _same_id("Olin Guha", "Olin Old")
    assert [l["slug"] for l in links] == ["olin-guha"]
    assert counts["unmatched"] == 1 and counts["duplicate_rmp_id"] == 0
    assert detail == [("Olin Old", "unmatched")]


def test_denied_then_clean_same_id_links_nothing():
    links, _, counts, detail = plan_seed([page("Denied Name", 1), page("Olin Guha", 1)],
                                         [cat("olin-guha", "olin guha")],
                                         is_denied=lambda k: k == "denied name")
    assert links == [] and counts["denied"] == 2 and detail == []


def test_clean_then_denied_same_id_links_nothing():
    links, _, counts, detail = plan_seed([page("Olin Guha", 1), page("Denied Name", 1)],
                                         [cat("olin-guha", "olin guha")],
                                         is_denied=lambda k: k == "denied name")
    assert links == [] and counts["denied"] == 2 and detail == []
