from pipeline.name_keys import plan_name_keys

PAGE_SLUG = {("Olin Guha", "CS"): "olin-guha"}
KEY_BY_SLUG = {"olin-guha": "olin guha"}


def review(id, name="Olin Guha", dept="CS", name_key=None):
    return {"id": id, "professor_name": name, "department": dept, "name_key": name_key}


def test_a_review_on_a_linked_page_gets_its_professors_key():
    assert plan_name_keys([review(1)], PAGE_SLUG, KEY_BY_SLUG) == [(1, "olin guha")]


def test_a_wrong_key_is_corrected_and_a_right_one_left_alone():
    reviews = [review(1, name_key="o guha"), review(2, name_key="olin guha")]
    assert plan_name_keys(reviews, PAGE_SLUG, KEY_BY_SLUG) == [(1, "olin guha")]


def test_a_review_on_no_linked_page_falls_back_to_its_own_name():
    assert plan_name_keys([review(1, name="Olin  GUHA", dept="Law")], PAGE_SLUG, KEY_BY_SLUG) == [(1, "olin guha")]


def test_a_keyed_review_on_no_linked_page_is_left_alone():
    assert plan_name_keys([review(1, dept="Law", name_key="o guha")], PAGE_SLUG, KEY_BY_SLUG) == []
