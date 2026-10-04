from pipeline.roster import resolve_roster, unique_slug

URL = "https://www.ratemyprofessors.com/professor/{}"


def page(name, pid, dept="Computer Science"):
    return {"name": name, "department": dept, "professor_url": URL.format(pid)}


def prof(slug, name_key, name=None):
    return {"slug": slug, "name": name or name_key.title(), "name_key": name_key,
            "department": "Computer Science", "college": "Khoury",
            "image_url": None, "focus_x": None, "focus_y": None}


def link(pid, slug, name="Someone"):
    return {"rmp_id": pid, "rmp_name": name, "rmp_department": None,
            "professor_url": URL.format(pid), "slug": slug, "match_method": "frozen"}


NO_DENY = lambda k: False  # noqa: E731


def test_unique_slug():
    assert unique_slug("jane-doe", set()) == "jane-doe"
    assert unique_slug("jane-doe", {"jane-doe"}) == "jane-doe-2"
    assert unique_slug("jane-doe", {"jane-doe", "jane-doe-2"}) == "jane-doe-3"


def test_frozen_link_wins_over_name():
    # Page 7 is frozen to olin-guha even though its name now reads differently.
    links, profs, counts = resolve_roster([page("O. Guha", 7)], [link(7, "olin-guha")],
                                          [prof("olin-guha", "olin guha")], NO_DENY)
    assert (links, profs, counts["known"]) == ([], [], 1)


def test_new_page_matching_an_existing_name_links_exact():
    links, profs, counts = resolve_roster([page("Olin Guha", 8)], [], [prof("olin-guha", "olin guha")], NO_DENY)
    assert profs == []
    assert links[0]["slug"] == "olin-guha" and links[0]["match_method"] == "exact"


def test_existing_professor_is_never_renamed():
    existing = prof("olin-guha", "olin guha", name="Olin Guha")
    _, profs, _ = resolve_roster([page("OLIN GUHA", 8)], [], [existing], NO_DENY)
    assert profs == [] and existing["name"] == "Olin Guha"


def test_new_professor_slug_never_collides():
    # "jane-doe" belongs to a different person (different name_key after aliasing).
    existing = prof("jane-doe", "jane doe smith")
    links, profs, counts = resolve_roster([page("Jane Doe", 9, dept="Law")], [], [existing], NO_DENY)
    assert profs[0]["slug"] == "jane-doe-2"
    assert profs[0]["name"] == "Jane Doe" and profs[0]["name_key"] == "jane doe"
    assert profs[0]["college"] == "Law"
    assert links[0]["slug"] == "jane-doe-2" and links[0]["match_method"] == "exact"
    assert counts["created"] == 1


def test_two_new_pages_for_one_new_person_make_one_professor():
    links, profs, _ = resolve_roster([page("Jane Doe", 9), page("Jane Doe", 10, dept="Khoury")], [], [], NO_DENY)
    assert len(profs) == 1 and [l["slug"] for l in links] == ["jane-doe", "jane-doe"]


def test_roster_skips_denied():
    links, profs, counts = resolve_roster([page("Jane Doe", 9)], [], [], lambda k: k == "jane doe")
    assert (links, profs, counts["denied"]) == ([], [], 1)


def test_page_without_an_id_is_skipped():
    _, _, counts = resolve_roster([{"name": "X", "department": None, "professor_url": None}], [], [], NO_DENY)
    assert counts["no_rmp_id"] == 1


def test_denied_id_blocks_a_name_variant_in_either_order():
    deny = lambda k: k == "jane doe"  # noqa: E731
    for pages in ([page("Jane Doe", 9), page("J Doe", 9)], [page("J Doe", 9), page("Jane Doe", 9)]):
        links, profs, _ = resolve_roster(pages, [], [], deny)
        assert links == [] and profs == []
