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
                         "text": "an answer", "by": "Ada", "finish": ""}


def test_evidence_is_frozen_into_a_tuple():
    mutable = ["a"]
    s = Situation(prompt="q", evidence=mutable)
    mutable.append("b")
    assert s.evidence == ("a",)


def test_an_explicit_id_is_respected():
    assert Response(text="t", id="fixed").id == "fixed"


def test_the_situation_config_reaches_the_judge():
    """The defect this closes made a whole study meaningless without failing
    anything: `commons` reads the regeneration rate a trial happened under, the
    arena put it in `Situation.meta`, `facts()` dropped it, and the judge fell
    back to its default — so sustainability was scored against a fixed
    regeneration rate while the sweep varied the regeneration rate.

    It was found by a bias probe, not by a test, and it is a test now.
    """
    from separatrix import Situation
    e = exchange("how many units?", "I take 12.", kind="harvest",
                 meta={"regeneration": 40.0, "pool": 100.0})
    assert e.facts()["regeneration"] == 40.0
    assert e.facts()["pool"] == 100.0
    assert e.facts()["text"] == "I take 12."


def test_the_exchanges_own_keys_beat_anything_in_the_meta():
    """Same rule as the journal's reserved keys, for the same reason: a
    situation carrying `text` must not be able to replace the reply the judge is
    supposed to be reading."""
    e = exchange("q?", "the real answer", kind="absent",
                 meta={"text": "a replacement", "kind": "present", "by": "someone"})
    facts = e.facts()
    assert facts["text"] == "the real answer"
    assert facts["kind"] == "absent"
    assert facts["by"] == "anonymous"
