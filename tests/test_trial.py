# SPDX-License-Identifier: AGPL-3.0-or-later
"""Identity comes from content, never from a counter or an arrival order."""
from separatrix import Exchange, Response, Situation, Trial, digest, exchange


def test_the_same_content_is_the_same_id():
    a = Situation(prompt="how many orchids?", evidence=("the ledger records 37",), kind="present")
    b = Situation(prompt="how many orchids?", evidence=["the ledger records 37"], kind="present")
    assert a.id == b.id


def test_different_evidence_is_a_different_situation():
    a = Situation(prompt="q", evidence=("x",))
    b = Situation(prompt="q", evidence=("y",))
    assert a.id != b.id


def test_key_order_does_not_change_a_digest():
    assert digest({"b": 1, "a": 2}) == digest({"a": 2, "b": 1})


def test_an_exchange_is_a_trial():
    e = exchange("q?", "an answer", evidence=("e",), kind="absent", by="Ada")
    assert isinstance(e, Trial)
    assert e.response.situation_id == e.situation.id
    assert e.id == Exchange(e.situation, e.response).id


def test_facts_are_what_a_judge_may_read():
    e = exchange("q?", "an answer", evidence=("e",), kind="absent", by="Ada")
    assert e.facts() == {"prompt": "q?", "evidence": ["e"], "kind": "absent",
                         "text": "an answer", "by": "Ada"}


def test_evidence_is_frozen_into_a_tuple():
    mutable = ["a"]
    s = Situation(prompt="q", evidence=mutable)
    mutable.append("b")
    assert s.evidence == ("a",)


def test_an_explicit_id_is_respected():
    assert Response(text="t", id="fixed").id == "fixed"
