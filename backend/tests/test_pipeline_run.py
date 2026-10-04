import pytest

from pipeline import run

URL = "https://www.ratemyprofessors.com/professor/"
TABLES = {
    "rmp_professors": [
        {"name": "Olin Guha", "department": "CS", "rating": 4.0, "num_ratings": 1,
         "would_take_again_pct": "90%", "level_of_difficulty": 3.0, "professor_url": URL + "1"},
        {"name": "Ada Lovelace", "department": "Math", "rating": 5.0, "num_ratings": 1,
         "would_take_again_pct": "100%", "level_of_difficulty": 2.0, "professor_url": URL + "2"},
    ],
    "rmp_links": [{"rmp_id": 1, "rmp_name": "Olin Guha", "rmp_department": "CS",
                   "professor_url": URL + "1", "slug": "olin-guha", "match_method": "frozen"}],
    "professors": [{"slug": "olin-guha", "name": "Olin Guha", "name_key": "olin guha",
                    "department": "CS", "college": "Khoury", "image_url": None,
                    "focus_x": None, "focus_y": None}],
    "catalog_courses": [{"code": "CS2500", "name": "Fundamentals", "department": "CS",
                         "subject": "CS", "search_text": "cs2500", "is_placeholder": False}],
    "rmp_reviews": [{"id": 10, "professor_name": "Olin Guha", "department": "CS", "name_key": None,
                     "course": "cs2500", "quality": 4.0, "difficulty": 3.0, "grade": "A",
                     "comment": "good", "visible": True}],
}


@pytest.fixture
def writes(monkeypatch):
    calls = []
    monkeypatch.setattr(run, "connect", lambda: object())
    monkeypatch.setattr(run, "fetch_all",
                        lambda conn, sql: [dict(r) for r in TABLES[sql.split(" FROM ")[1].split()[0]]])
    monkeypatch.setattr(run.roster, "apply_roster", lambda conn, l, p: calls.append(("roster", l, p)))
    monkeypatch.setattr(run.course_codes, "apply_codes", lambda conn, p: calls.append(("codes", p)) or 0)
    monkeypatch.setattr(run.name_keys, "apply_name_keys", lambda conn, p: calls.append(("name_keys", p)) or 0)
    monkeypatch.setattr(run.read_models, "write", lambda conn, *a: calls.append(("read_models",)))
    return calls


def test_a_failed_verify_writes_nothing(writes):
    assert run.main([]) == 1                      # 2 professors, far under MIN_PROFESSORS
    assert writes == []


def test_a_dry_run_writes_nothing(writes, monkeypatch):
    monkeypatch.setattr(run.read_models, "verify", lambda *a: [])
    assert run.main(["--dry-run"]) == 0
    assert writes == []


def test_writes_happen_after_verify_in_order(writes, monkeypatch):
    monkeypatch.setattr(run.read_models, "verify", lambda *a: [])
    assert run.main([]) == 0
    assert [c[0] for c in writes] == ["roster", "codes", "name_keys", "read_models"]
    _, new_links, new_professors = writes[0]
    assert [l["rmp_id"] for l in new_links] == [2] and [p["name"] for p in new_professors] == ["Ada Lovelace"]
    assert writes[1][1] == [(10, "CS2500")]
    assert writes[2][1] == [(10, "olin guha")]
