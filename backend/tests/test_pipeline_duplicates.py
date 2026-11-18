import pytest

from pipeline import duplicates
from pipeline.duplicates import name_parts, near_misses, nickname_match, nickname_merges


def prof(slug, name_key, dept="Physics", origin="rmp"):
    return {"slug": slug, "name": name_key.title(), "name_key": name_key, "department": dept, "origin": origin}


def test_name_parts():
    assert name_parts("tom kelley") == ("tom", "kelley")
    assert name_parts("j. timothy sage") == (None, "sage")              # an initial has nothing to compare
    assert name_parts("kimberly silverman (craven)") == ("kimberly", "silverman")
    assert name_parts("cher") == (None, None)


def test_nickname_match():
    assert nickname_match("tom", "thomas") and nickname_match("thomas", "tom")
    assert nickname_match("steve", "stephen") and nickname_match("steve", "steven")
    assert nickname_match("ted", "edward") and nickname_match("ted", "theodore")
    assert not nickname_match("stephen", "steven")          # two formal names: a person decides
    assert not nickname_match("dan", "danielle")            # a prefix is not a nickname
    assert not nickname_match("tom", "tom")
    assert duplicates.sure_nickname("tom", "thomas") and duplicates.sure_nickname("tom", "tommy")
    assert not duplicates.sure_nickname("pat", "patricia") and not duplicates.sure_nickname("steve", "stephen")


def test_an_rmp_nickname_profile_folds_into_the_banner_one():
    merges, review = nickname_merges([prof("tom-kelley", "tom kelley"),
                                      prof("thomas-kelley", "thomas kelley", origin="banner")])
    assert (merges, review) == ({"tom-kelley": "thomas-kelley"}, [])


def test_the_banner_profile_survives_even_under_the_nickname():
    merges, _ = nickname_merges([prof("thomas-kelley", "thomas kelley"),
                                 prof("tom-kelley", "tom kelley", origin="banner")])
    assert merges == {"thomas-kelley": "tom-kelley"}


def test_two_rmp_profiles_keep_the_formal_name():
    merges, _ = nickname_merges([prof("tony-russo", "tony russo"), prof("anthony-russo", "anthony russo")])
    assert merges == {"tony-russo": "anthony-russo"}


def test_a_nickname_with_two_formal_names_is_only_reviewed():
    # Pat may be Patrick, not this Patricia.
    merges, [(_, _, why)] = nickname_merges([prof("pat-smith", "pat smith"),
                                             prof("patricia-smith", "patricia smith", origin="banner")])
    assert merges == {} and "more than one name" in why
    index = duplicates.NicknameIndex([prof("patricia-smith", "patricia smith", origin="banner")])
    assert index.target("pat smith", "Physics") is None


def test_a_suffix_is_not_a_last_name():
    assert name_parts("tom jones jr.") == ("tom", "jones")
    assert name_parts("thomas smith iii") == ("thomas", "smith")
    assert nickname_merges([prof("tom-jones-jr", "tom jones jr"),
                            prof("thomas-smith-jr", "thomas smith jr", origin="banner")]) == ({}, [])


def test_a_profile_a_reviewer_linked_by_hand_is_only_reviewed():
    merges, [(_, _, why)] = nickname_merges([prof("tom-x", "tom x"), prof("thomas-x", "thomas x", origin="banner")],
                                            pinned={"tom-x"})
    assert merges == {} and "by hand" in why


def test_two_banner_profiles_are_left_to_a_person():
    merges, [(_, _, why)] = nickname_merges([prof("dan-cooper", "dan cooper", origin="banner"),
                                             prof("daniel-cooper", "daniel cooper", origin="banner")])
    assert merges == {} and "Banner" in why


def test_different_departments_never_merge():
    profs = [prof("tim-blank", "tim blank", "Management"),
             prof("timothy-blank", "timothy blank", "Communication Studies", "banner")]
    assert nickname_merges(profs) == ({}, [])
    [(_, _, why)] = near_misses(profs, {})
    assert "different departments" in why


def test_a_third_candidate_makes_it_a_review():
    merges, review = nickname_merges([prof("tom-x", "tom x"), prof("thomas-x", "thomas x", origin="banner"),
                                      prof("tommy-x", "tommy x")])
    assert merges == {} and review


def test_two_formal_names_one_nickname_could_be_is_a_review():
    # "Steve Clark" could be Stephen or Steven.
    merges, review = nickname_merges([prof("steve-clark", "steve clark"),
                                      prof("stephen-clark", "stephen clark", origin="banner"),
                                      prof("steven-clark", "steven clark", origin="banner")])
    assert merges == {} and review


def test_a_prefix_is_only_a_review():
    profs = [prof("sidd-pant", "sidd pant"), prof("siddhartha-pant", "siddhartha pant", origin="banner")]
    assert nickname_merges(profs) == ({}, [])
    [(_, _, why)] = near_misses(profs, {})
    assert "start of the other" in why


def test_no_department_no_merge():
    assert nickname_merges([prof("brad-b", "brad beakes", None), prof("bradley-b", "bradley beakes", None)]) == ({}, [])


def test_not_duplicates_vetoes_a_pair(monkeypatch):
    monkeypatch.setattr(duplicates, "NOT_DUPLICATES", {frozenset(("tom kelley", "thomas kelley"))})
    profs = [prof("tom-kelley", "tom kelley"), prof("thomas-kelley", "thomas kelley", origin="banner")]
    assert nickname_merges(profs) == ({}, [])
    assert near_misses(profs, {}) == []


@pytest.mark.parametrize("key,dept,expected", [
    ("tom kelley", "Physics", "thomas-kelley"),
    ("tom kelley", "Chemistry", None),
    ("thomas kelley", "Physics", None),         # exact names are not this index's job
])
def test_index_target(key, dept, expected):
    index = duplicates.NicknameIndex([prof("thomas-kelley", "thomas kelley", origin="banner")])
    found = index.target(key, dept)
    assert (found["slug"] if found else None) == expected
