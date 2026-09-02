# SPDX-License-Identifier: AGPL-3.0-or-later
"""Replicates that share a cache are one draw copied.

The defect these close was live and shipped. `Responder` owned one cache for a
whole sweep, and the sweep called the same arena once per replicate, so the
second replicate was served the first one's answers. The recorded run says so
plainly: generation 0 of draw 2 was twenty cache hits and zero calls.

What that costs is not money, it is the noise floor. Resolution is derived from
the spread between replicates, and copies do not spread — so the floor comes out
below the sampler's own variability and the search believes it can resolve
things it cannot. This library exists to refuse exactly that, and it was doing
it to itself.
"""
import json

import pytest
from fake_chat import FakeChat
from separatrix import (Agent, Budget, Coordinate, Exchange, FoldJudge, Journal,
                        Outcome, Provenance, Responder, Situation, Validated,
                        Validation, Verdict, draw_label, sweep)
from separatrix.judge import Tier

SIT = Situation(prompt="who tends the south glasshouse?", kind="absent")
COORD = Coordinate("w", 0.0, 4.0)
DECLINED = Outcome(measure=lambda rs: sum(r.verdict.is_pass() for r in rs) / len(rs),
                   threshold=0.5, name="decline rate")


def judge():
    inner = FoldJudge(lambda f: f["text"] == "I don't know.", id="decline@1")
    return Validated(inner=inner, measured=Validation(
        tier=Tier.FOLD, verdict=Verdict.PASSED, cases=40, discrimination=1.0,
        note="probed"))


def alternating():
    """Answers that differ call to call — a sampler with real variability, which
    is the only kind whose noise is worth measuring."""
    chat = FakeChat(lambda s, u: "I don't know." if len(chat.calls) % 2 else "Ada.")
    return chat


class Garden:
    """Four agents, one genome, one question, through a Responder.

    A miniature of `Evolution`: what matters is that answers arrive through a
    cache, which is where a replicate can quietly become a copy.
    """

    def __init__(self, chat, agents=4):
        self.responder = Responder(chat)
        self.agents = [Agent(id=f"a{i}", genome="g") for i in range(agents)]

    def draw(self, label):
        self.responder.separate(label)

    def run(self, config, judge):
        return [judge.rule(Exchange(SIT, self.responder(a, SIT))) for a in self.agents]


class SharedCacheGarden(Garden):
    """The same arena as it was before the fix: no way to separate draws.

    Kept as a class rather than a flag because it is what a third-party arena
    looks like from the sweep's side, and the sweep has to behave well against
    one it did not write.
    """

    draw = None


# ── the defect, watched failing ─────────────────────────────────────────────

def test_a_shared_cache_reports_a_noise_floor_that_is_not_the_samplers():
    """The gate. Same sampler, same arena logic, same budget — and the version
    that cannot separate its draws measures zero variability in a sampler that
    alternates every call."""
    shared = sweep(SharedCacheGarden(alternating()), judge(), COORD, DECLINED,
                   budget=Budget(runs=12), replicates=3)
    assert shared.noise == 0.0, "a cache that spans draws hides the sampler entirely"

    separated = sweep(Garden(alternating()), judge(), COORD, DECLINED,
                      budget=Budget(runs=12), replicates=3)
    assert separated.noise > 0.0
    # And it is not a rounding difference: the whole spread was being suppressed.
    assert separated.noise > 0.4


def test_a_second_replicate_pays_for_its_own_answers():
    """Six samples, twenty-four agent-questions, and the calls that are actually
    made are the ones a draw has not already asked.

    Paired: the two ends ask an identical population an identical question, so
    replicate 0 is answered once and reused at both — three calls, and the
    saving is the whole point of pairing. Unpaired: six.
    """
    paired, unpaired = alternating(), alternating()
    for chat, is_paired, calls in ((paired, True, 3), (unpaired, False, 6)):
        arena = Garden(chat)
        sweep(arena, judge(), COORD, DECLINED, budget=Budget(runs=12),
              replicates=3, paired=is_paired)
        assert len(chat.calls) == calls
        assert arena.responder.misses == calls
        assert arena.responder.hits == 24 - calls   # four agents x six samples


def test_an_arena_that_cannot_separate_draws_is_warned_about_not_trusted():
    """Absence is reported. An arena with nothing cached is entitled to say
    replicates are already independent; one that says nothing gets no benefit of
    the doubt."""
    with pytest.warns(RuntimeWarning, match="no draw"):
        sweep(SharedCacheGarden(alternating()), judge(), COORD, DECLINED,
              budget=Budget(runs=12), replicates=3)


# ── the key, and what belongs in it ─────────────────────────────────────────

def test_the_draw_is_part_of_the_response_key():
    a, r = Agent(id="a0", genome="g"), Responder(FakeChat("x"))
    first = r.key(a, SIT)
    r.separate("rep1")
    assert r.key(a, SIT) != first
    r.separate("")
    assert r.key(a, SIT) == first, "the draw label is the only thing that moved"


def test_separating_partitions_the_cache_rather_than_emptying_it():
    """A repeated label must hit again, or common random numbers cost full
    price and the pairing is decorative."""
    chat = alternating()
    r = Responder(chat)
    a = Agent(id="a0", genome="g")
    r.separate("rep0"); r(a, SIT)
    r.separate("rep1"); r(a, SIT)
    r.separate("rep0"); r(a, SIT)
    assert len(chat.calls) == 2 and (r.hits, r.misses) == (1, 2)


# ── pairing across values, independence across replicates ───────────────────

def test_paired_draws_repeat_across_values_and_never_within_one():
    values, reps = [0.0, 4.0, 2.0], range(3)
    paired = {v: [draw_label(v, i, paired=True) for i in reps] for v in values}
    assert all(len(set(labels)) == 3 for labels in paired.values()), \
        "replicates at one value must be different draws — the noise is measured there"
    assert paired[0.0] == paired[4.0] == paired[2.0], \
        "the same replicate index at two values is common random numbers"

    unpaired = {v: [draw_label(v, i, paired=False) for i in reps] for v in values}
    assert len({label for labels in unpaired.values() for label in labels}) == 9


def test_pairing_does_not_touch_the_measured_noise():
    """Pairing sharpens the comparison BETWEEN values. The floor is estimated
    from the spread WITHIN one, so it must come out the same either way."""
    a = sweep(Garden(alternating()), judge(), COORD, DECLINED,
              budget=Budget(runs=12), replicates=3, paired=True)
    b = sweep(Garden(alternating()), judge(), COORD, DECLINED,
              budget=Budget(runs=12), replicates=3, paired=False)
    assert a.noise == b.noise


# ── the record ──────────────────────────────────────────────────────────────

def test_the_journal_says_which_scope_the_run_used(tmp_path):
    path = tmp_path / "j.jsonl"
    with Journal(path, Provenance(served="fake-model-7B")) as j:
        sweep(Garden(alternating()), judge(), COORD, DECLINED,
              budget=Budget(runs=12), replicates=3, journal=j, paired=True)

    records = [json.loads(ln) for ln in path.read_text().splitlines()]
    scope = next(r for r in records if r["t"] == "draws")
    assert scope["separated"] is True and scope["paired"] is True
    assert scope["arena"] == "Garden"

    samples = [r for r in records if r["t"] == "sample"]
    assert {s["draw"] for s in samples} == {"rep0", "rep1", "rep2"}
