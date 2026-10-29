import os, sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

import photo_research as pr


def test_alias_index_links_both_directions():
    idx = pr.build_alias_index()
    # ALIAS_MAP has "bill goldman" / "william (bill) goldman" -> "william goldman"
    eq = pr.aliases_for("Bill Goldman", idx)
    assert "william goldman" in eq
    assert "bill goldman" in eq


def test_aliases_for_unknown_name_returns_self_only():
    idx = pr.build_alias_index()
    eq = pr.aliases_for("Zzz Nobodyson", idx)
    assert eq == {"zzz nobodyson"}


def test_name_match_exact_and_first_last():
    idx = pr.build_alias_index()
    assert pr.name_matches("Jonathan Bell", "Jonathan Bell", idx)
    # middle name on page, not in NEU name
    assert pr.name_matches("Jonathan Bell", "Jonathan P. Bell", idx)
    # middle name in NEU name, not on page
    assert pr.name_matches("Jonathan P Bell", "Jonathan Bell", idx)


def test_name_match_rejects_surname_only_and_wrong_first():
    idx = pr.build_alias_index()
    # same surname, different first name, no alias -> reject (collision)
    assert not pr.name_matches("Jonathan Bell", "Sarah Bell", idx)
    # only surname present -> reject
    assert not pr.name_matches("Jonathan Bell", "Bell", idx)


def test_name_match_accepts_alias():
    idx = pr.build_alias_index()
    # alias pair from ALIAS_MAP
    assert pr.name_matches("Virgil Pavlu", "Virgiliu Pavlu", idx)


def test_dept_to_college_known_and_unknown():
    assert pr.dept_to_college("Computer Science") == "Khoury"
    assert pr.dept_to_college("Economics") == "CSSH"
    assert pr.dept_to_college("Underwater Basket Weaving") == "Unknown"


def test_dept_to_college_matches_double_space_college_map_keys():
    # Only COLLEGE_MAP has these, spelled with "&"; get_college matches the stripped form.
    assert pr.dept_to_college("Counseling  Educational Psych") == "Health Sciences"
    assert pr.dept_to_college("Computer  Informational Tech.") == "Khoury"


def test_is_plausible_photo_url():
    assert pr.is_plausible_photo_url("https://x.edu/uploads/jane-doe-400x400.jpg")
    assert pr.is_plausible_photo_url("https://x.edu/p.png?cb=1")
    assert not pr.is_plausible_photo_url("https://x.edu/logo.png")          # SKIP pattern
    assert not pr.is_plausible_photo_url("https://x.edu/group-photo.jpg")   # SKIP pattern
    assert not pr.is_plausible_photo_url("https://x.edu/profile")           # no extension


def test_dept_to_college_supplemental_mapping():
    # Department strings present in the data but absent from pipeline.names.COLLEGE_MAP
    assert pr.dept_to_college("Art and Design") == "CAMD"
    assert pr.dept_to_college("Chemistry  Chemical Biology") == "Science"   # double space
    assert pr.dept_to_college("Mech  Industrial Engineering") == "Engineering"
    # genuinely unmapped admin departments stay Unknown
    assert pr.dept_to_college("Army ROTC") == "Unknown"
    assert pr.dept_to_college("") == "Unknown"
    assert pr.dept_to_college(float("nan")) == "Unknown"
