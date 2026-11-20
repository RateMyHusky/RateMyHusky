import pathlib

import programs

BACKEND = pathlib.Path(__file__).resolve().parent.parent
REPO = BACKEND.parent


def test_the_two_copies_are_identical():
    assert (BACKEND / "programs.json").read_bytes() == (REPO / "frontend/src/data/programs.json").read_bytes()


def test_names_load_and_other_is_reserved():
    assert len(programs.MAJORS) > 50 and len(programs.MINORS) > 50
    assert programs.OTHER == "other" and "other" not in programs.MAJORS | programs.MINORS
