from pipeline.roster import (carry_photos, merged_slugs, plan_relinks, recollege, relink, remap_slugs,
                             resolve_roster, unique_slug)

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


def test_recollege_corrects_only_a_college_that_left_college_map():
    stale = {**prof("jane-doe", "jane doe"), "department": "Counseling & Educational Psych",
             "college": "Professional Studies"}
    unmapped = {**prof("ada-l", "ada l"), "department": "Underwater Basket Weaving"}
    assert recollege([prof("olin-guha", "olin guha"), stale, unmapped]) == [("jane-doe", "Health Sciences")]


def test_recollege_matches_a_department_spelled_with_the_ampersand_stripped():
    stale = {**prof("jane-doe", "jane doe"), "department": "Counseling  Educational Psych",
             "college": "Professional Studies"}
    assert recollege([stale]) == [("jane-doe", "Health Sciences")]


def test_new_professor_name_is_tidied_but_key_is_not():
    links, profs, _ = resolve_roster([page("THOMAS SEXTON", 9)], [], [], NO_DENY)
    assert profs[0]["name"] == "Thomas Sexton"
    assert profs[0]["name_key"] == "thomas sexton"
    assert links[0]["rmp_name"] == "THOMAS SEXTON"


# ── Merging two profiles of one person (RMP_MANUAL_LINKS) ─────────────────────
# RMP had "Ant Woodall" (the ratings) and "Anthony Woodall" (none); both were
# frozen to their own professor. RMP_MANUAL_LINKS now says ant -> anthony.
WOODALL_PAGES = [page("Ant  Woodall", 1), page("Anthony Woodall", 2)]
WOODALL_LINKS = [link(1, "ant-woodall"), link(2, "anthony-woodall")]
WOODALL_PROFS = [prof("ant-woodall", "ant woodall"), prof("anthony-woodall", "anthony woodall")]


def test_a_manual_link_moves_a_frozen_link_and_merges_the_professor():
    moves, skipped = plan_relinks(WOODALL_PAGES, WOODALL_LINKS, WOODALL_PROFS)
    assert (moves, skipped) == ({1: ("ant-woodall", "anthony-woodall")}, {})
    after = relink(WOODALL_LINKS, moves)
    assert [(l["slug"], l["match_method"]) for l in after] == [("anthony-woodall", "manual"),
                                                                ("anthony-woodall", "frozen")]
    assert merged_slugs(WOODALL_PROFS, after, moves) == {"ant-woodall": "anthony-woodall"}


def test_an_alias_map_spelling_never_moves_a_frozen_link():
    # ALIAS_MAP has "matt lee" -> "matthew lee"; this Matt Lee may be someone else.
    moves, _ = plan_relinks([page("Matt Lee", 7)], [link(7, "matt-lee")],
                            [prof("matt-lee", "matt lee"), prof("matthew-lee", "matthew lee")])
    assert moves == {}


def test_a_name_matched_as_written_never_moves_a_frozen_link():
    moves, _ = plan_relinks([page("Olin Guha", 7)], [link(7, "guha-2")],
                            [prof("guha-2", "o guha"), prof("olin-guha", "olin guha")])
    assert moves == {}


def test_a_link_a_reviewer_settled_in_the_database_is_never_moved():
    settled = [{**link(1, "ant-woodall-2"), "match_method": "manual"}, link(2, "anthony-woodall")]
    moves, skipped = plan_relinks(WOODALL_PAGES, settled, WOODALL_PROFS + [prof("ant-woodall-2", "ant woodall")])
    assert (moves, skipped) == ({}, {"manual_in_db": 1})


def test_a_target_name_two_professors_share_is_skipped():
    profs = WOODALL_PROFS + [{**prof("anthony-woodall-2", "anthony woodall"), "origin": "banner"}]
    moves, skipped = plan_relinks(WOODALL_PAGES, WOODALL_LINKS, profs)
    assert (moves, skipped) == ({}, {"ambiguous": 1})
    assert merged_slugs(profs, WOODALL_LINKS, moves) == {}


def test_a_manual_link_to_a_professor_not_on_the_roster_moves_nothing():
    moves, skipped = plan_relinks([page("Ant Woodall", 1)], [link(1, "ant-woodall")],
                                  [prof("ant-woodall", "ant woodall")])
    assert (moves, skipped) == ({}, {"no_target": 1})


def test_a_merge_is_still_known_on_every_later_run():
    # The link moved last week; nothing moves now, but rows naming ant-woodall must still follow.
    after = [link(1, "anthony-woodall"), link(2, "anthony-woodall")]
    moves, _ = plan_relinks(WOODALL_PAGES, after, WOODALL_PROFS)
    assert moves == {}
    assert merged_slugs(WOODALL_PROFS, after, moves) == {"ant-woodall": "anthony-woodall"}


def test_a_professor_keeping_another_page_is_not_merged():
    links = WOODALL_LINKS + [link(3, "ant-woodall")]
    moves = {1: ("ant-woodall", "anthony-woodall")}
    assert merged_slugs(WOODALL_PROFS, relink(links, moves), moves) == {}


def test_a_banner_or_survey_professor_is_never_merged_away():
    profs = [{**prof("ant-woodall", "ant woodall"), "origin": "banner"}, prof("anthony-woodall", "anthony woodall")]
    assert merged_slugs(profs, [link(2, "anthony-woodall")], {}) == {}


def test_a_chain_of_merges_resolves_to_its_end():
    profs = [prof("a", "a x"), prof("b", "b x"), prof("c", "c x")]
    assert merged_slugs(profs, [link(9, "c")], {1: ("a", "b"), 2: ("b", "c")}) == {"a": "c", "b": "c"}


def test_rows_naming_a_merged_slug_follow_it():
    rows = [{"professor_slug": "ant-woodall", "x": 1}, {"professor_slug": "olin-guha"}, {"professor_slug": None}]
    assert [r["professor_slug"] for r in remap_slugs(rows, {"ant-woodall": "anthony-woodall"})] == \
        ["anthony-woodall", "olin-guha", None]


def test_a_merge_keeps_the_merged_professors_photo():
    ant = {**prof("ant-woodall", "ant woodall"), "image_url": "ant.jpg", "focus_x": 50.1, "focus_y": 37.3}
    anthony = prof("anthony-woodall", "anthony woodall")
    profs, photos = carry_photos([ant, anthony], {"ant-woodall": "anthony-woodall"})
    assert photos == {"anthony-woodall": {"image_url": "ant.jpg", "focus_x": 50.1, "focus_y": 37.3}}
    assert {p["slug"]: p["image_url"] for p in profs}["anthony-woodall"] == "ant.jpg"


def test_a_merge_never_replaces_the_survivors_own_photo():
    ant = {**prof("ant-woodall", "ant woodall"), "image_url": "ant.jpg"}
    anthony = {**prof("anthony-woodall", "anthony woodall"), "image_url": "anthony.jpg"}
    profs, photos = carry_photos([ant, anthony], {"ant-woodall": "anthony-woodall"})
    assert photos == {} and {p["slug"]: p["image_url"] for p in profs}["anthony-woodall"] == "anthony.jpg"
