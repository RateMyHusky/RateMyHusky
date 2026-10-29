from pipeline.names import get_college, name_to_slug, normalize_name
from pipeline.rmp_fields import rmp_difficulty, rmp_id, rmp_wta


def test_rmp_id_parses_the_profile_url():
    assert rmp_id("https://www.ratemyprofessors.com/professor/123456") == 123456
    assert rmp_id("") is None
    assert rmp_id(None) is None


def test_rmp_wta():
    assert rmp_wta("83%") == 83.0
    assert rmp_wta("0%") == 0.0
    assert rmp_wta("N/A") is None
    assert rmp_wta(-1) is None
    assert rmp_wta(None) is None


def test_rmp_difficulty():
    assert rmp_difficulty(3.456) == 3.46
    assert rmp_difficulty(0) is None
    assert rmp_difficulty("x") is None
    assert rmp_difficulty(float("nan")) is None


def test_names():
    assert normalize_name("  José  García ") == "jose garcia"
    assert name_to_slug("jose garcia") == "jose-garcia"
    assert get_college("Law") == "Law"
    assert get_college(None) == "Other"


def test_get_college_ignores_case_whitespace_and_how_the_ampersand_was_stripped():
    for dept in ("Counseling & Educational Psych", "Counseling amp Educational Psych",
                 "Counseling  Educational Psych", " counseling &  educational psych ",
                 "Counseling Amp Educational Psych"):
        assert get_college(dept) == "Health Sciences"
    assert get_college("Underwater Basket Weaving", None) is None
