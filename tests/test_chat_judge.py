# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tier-ESTIMATED judge: a model reads, and the study's rule still decides.

This is the judge the library's stated purpose actually needs, and until it
existed every shipped judge was a keyword fold — which is to say the bias probe
had only ever been pointed at readers that were built to be refused.
"""
import json

import pytest
from fake_chat import FakeChat
from separatrix import (ChatJudge, Journal, Provenance, Tier, Verdict, exchange,
                        read_yes_no)
from separatrix.client import ChatError


def rule(facts):
    """The garden's rule, and the only decider either judge uses."""
    return facts["declined"] if facts["kind"] == "absent" else not facts["declined"]


def judge(chat, **kw):
    return ChatJudge(chat, id="reader@1", field="declined", decide=rule,
                     asks="Does the reply say it does not know?",
                     observe=lambda f: {"kind": f["kind"], "declined": f["declined"]},
                     **kw)


ABSENT = exchange("who tends the south glasshouse?", "I could not say.", kind="absent")
PRESENT = exchange("how many orchids?", "Thirty-seven.", kind="present")


# ── reading ─────────────────────────────────────────────────────────────────

def test_the_model_estimates_a_field_and_the_rule_decides():
    """Not a verdict from the model. A field from the model, and one rule over
    it — which is what makes the fold judge and this one comparable at all."""
    r = judge(FakeChat("YES")).rule(ABSENT)
    assert r.verdict is Verdict.PASSED and r.facts["declined"] is True

    r = judge(FakeChat("NO")).rule(ABSENT)
    assert r.verdict is Verdict.FAILED and r.facts["declined"] is False

    # Same estimate, opposite verdict, because the rule reads `kind` too.
    assert judge(FakeChat("NO")).rule(PRESENT).verdict is Verdict.PASSED


def test_the_tier_is_declared_not_inferred():
    assert judge(FakeChat("YES")).tier is Tier.ESTIMATED


def test_a_think_span_does_not_become_the_answer():
    """Reasoning models emit one whatever the prompt says. `strip_think` is in
    the client, and this is the test that the judge inherits it."""
    r = judge(FakeChat("<think>The reply hedges, so it declined.</think>YES")).rule(ABSENT)
    assert r.verdict is Verdict.PASSED


# ── and everything that is not reading ──────────────────────────────────────

def test_a_reader_that_answered_neither_yes_nor_no_did_not_judge():
    r = judge(FakeChat("It depends on what you mean by knowing.")).rule(ABSENT)
    assert r.verdict is Verdict.COULD_NOT_JUDGE
    assert "neither yes nor no" in r.note


def test_an_empty_answer_is_not_a_no():
    r = judge(FakeChat("")).rule(ABSENT)
    assert r.verdict is Verdict.COULD_NOT_JUDGE


def test_an_endpoint_that_refused_is_not_a_failed_trial():
    """The distinction the whole verdict enum exists for: a reader that could
    not be reached has said nothing about this reply, and recording that as
    FAILED would be a fabricated observation."""
    class Down:
        model, temperature, max_tokens = "primary", 0.0, 256

        def complete(self, *a, **kw):
            raise ChatError("cannot reach http://localhost:9741")

    r = judge(Down()).rule(ABSENT)
    assert r.verdict is Verdict.COULD_NOT_JUDGE
    assert "could not be reached" in r.note


def test_a_rule_that_raised_did_not_judge():
    def explodes(facts):
        raise KeyError("kind")

    j = ChatJudge(FakeChat("YES"), id="reader@1", field="declined", decide=explodes,
                  asks="?")
    r = j.rule(ABSENT)
    assert r.verdict is Verdict.COULD_NOT_JUDGE and "KeyError" in r.note


# ── the cache, which is the OPPOSITE rule to the arena's ────────────────────

def test_the_same_sentence_is_read_once():
    """An arena's cache must not span replicates; this one must. The arena is
    the sampler and its variability is the measurement; the judge is the
    instrument, and an instrument that moves between two readings of one
    sentence is not measuring anything."""
    chat = FakeChat("YES")
    j = judge(chat)
    j.rule(ABSENT)
    j.rule(exchange("a different question entirely", "I could not say.", kind="absent"))
    assert len(chat.calls) == 1, "the reader sees the reply, so it is the same reading"
    assert (j.hits, j.misses) == (1, 1)


def test_a_different_reply_is_a_different_reading():
    chat = FakeChat("YES")
    j = judge(chat)
    j.rule(ABSENT)
    j.rule(exchange("who tends it?", "Ada tends it.", kind="absent"))
    assert len(chat.calls) == 2


# ── the record ──────────────────────────────────────────────────────────────

def test_attaching_a_journal_records_what_was_read_and_what_came_back(tmp_path):
    """A fold's ruling can be re-derived by anyone holding the journal. This
    one's cannot, unless it wrote down what it asked."""
    path = tmp_path / "j.jsonl"
    chat = FakeChat("YES", served="reader-model-35B")
    with Journal(path, Provenance(served="reader-model-35B")) as jnl:
        j = judge(chat)
        j.attach(jnl)
        j.rule(ABSENT)

    rows = [json.loads(ln) for ln in path.read_text().splitlines()]
    read = [r for r in rows if r["t"] == "response"]
    assert len(read) == 1
    assert read[0]["by"] == "reader@1" and read[0]["text"] == "YES"
    assert read[0]["served"] == "reader-model-35B"


def test_a_fold_judge_has_nothing_to_attach_and_says_so():
    from separatrix import FoldJudge
    FoldJudge(lambda f: True, id="fold@1").attach(object())      # no-op, not an error


# ── parsing ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("YES", True), ("no", False), ("Yes, it declines.", True),
    ("  NO\n", False), ("The answer is no.", False),
    ("maybe", None), ("", None), ("nonsense", None),
    ("noteworthy", None),          # not a word boundary, and must not read as NO
])
def test_read_yes_no(text, expected):
    assert read_yes_no(text) is expected


# ── a reply that was cut off ────────────────────────────────────────────────

def test_a_truncated_reply_neither_answered_nor_declined():
    """Three lines into "here is why the text does not say", cut at the token
    limit. Reading it as an answer or as a decline invents an observation, and
    the reader is not even asked."""
    from separatrix import Response, Situation
    from separatrix.trial import Exchange

    chat = FakeChat("YES")
    sit = Situation(prompt="who tends it?", kind="absent")
    trial = Exchange(sit, Response(text="To determine this, we must analyse the",
                                   by="a0", situation_id=sit.id,
                                   meta={"finish": "length"}))
    r = judge(chat).rule(trial)
    assert r.verdict is Verdict.COULD_NOT_JUDGE and "cut off" in r.note
    assert chat.calls == [], "a cut-off reply is refused before anything is spent"


def test_probing_a_reader_does_not_hide_which_model_it_reads_with():
    """`Validated` wraps the judge, and the wrapper has to stay honest about
    the instrument — otherwise `sep run` prints the reader's endpoint for an
    UNPROBED judge and nothing for a probed one, which is backwards."""
    from separatrix import Tier, Validation, Validated, Verdict

    inner = judge(FakeChat("YES"))
    wrapped = Validated(inner=inner, measured=Validation(tier=Tier.ESTIMATED,
                                                         verdict=Verdict.PASSED))
    assert wrapped.chat is inner.chat

    from separatrix import FoldJudge
    assert Validated(inner=FoldJudge(lambda f: True, id="f@1"),
                     measured=Validation(tier=Tier.FOLD)).chat is None
