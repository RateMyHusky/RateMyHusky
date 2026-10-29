"""Live check of the reviewer prompt against the real model. Skipped unless
RUN_GROQ_LIVE=1 and the Groq key groq1 are set:

    cd backend && RUN_GROQ_LIVE=1 groq1=<key> python -m pytest tests/test_review_agent_live.py -q
"""

import os

import pytest

import review_agent as ra
from rag.key_pool import KeyPool, load_entries
from tests.test_review_agent import _bomb_rows, _row
from tests.varied_ratings import VARIED_RATINGS

pytestmark = pytest.mark.skipif(not (os.getenv("RUN_GROQ_LIVE") == "1" and os.getenv("groq1")),
                                reason="set RUN_GROQ_LIVE=1 and groq1 to call the real model")


def _answer(group):
    groq = ra.Groq(KeyPool(load_entries()))
    taught = {r["course_code"]: True for r in group}
    text = groq.ask(ra.build_messages(group, [], taught))
    assert text is not None, "Groq returned no answer"
    print(text)
    return ra.parse_decision(text)


def test_the_bomb_group_is_recommended_for_rejection():
    answer = _answer(_bomb_rows())
    assert answer["recommend_reject"] is True


def test_an_end_of_term_rush_of_varied_ratings_is_approved():
    group = [_row(i, "burst_prof", i * 3, comment=v["comment"], rating=v["rating"], course_code=v["course"])
             for i, v in enumerate(VARIED_RATINGS)]
    answer = _answer(group)
    assert answer["decision"] == "approve" and answer["recommend_reject"] is False
    assert ra.final_decision(group, answer) == "approve"


def test_herc_refers_to_the_professor():
    comments = ["But Prof. Herc really tries his hardest. Exams are fair.", "Prof Herc is super nice and cares."]
    text = ra.Groq(KeyPool(load_entries())).ask(ra.nickname_messages("Iraklis Tsekourakis", {"Herc": comments}))
    assert text is not None, "Groq returned no answer"
    print(text)
    assert ra.parse_nicknames(text, ["Herc"]) == {"Herc": True}
