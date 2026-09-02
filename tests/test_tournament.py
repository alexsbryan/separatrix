# SPDX-License-Identifier: AGPL-3.0-or-later
"""Agents playing each other, and a payoff matrix as the coordinate."""
import json

import pytest
from fake_chat import FakeChat
from separatrix import (Agent, Budget, Coordinate, FoldJudge, Journal, Outcome,
                        Provenance, Responder, Tier, Tournament, Validated,
                        Validation, Verdict, sweep)

COOPERATOR = "Always cooperate."
DEFECTOR = "Always defect."
TIT_FOR_TAT = "Cooperate first, then copy what they did last."

PEOPLE = [Agent(id="c", genome=COOPERATOR), Agent(id="d", genome=DEFECTOR),
          Agent(id="t", genome=TIT_FOR_TAT)]


def chat():
    def answer(system, user):
        if system == COOPERATOR:
            return "I cooperate."
        if system == DEFECTOR:
            return "I defect."
        # The history lines sit in the MIDDLE of the prompt; the last line is
        # the question. Reading splitlines()[-1] made tit-for-tat unconditionally
        # kind, which looked like an arena bug and was a fixture one.
        rounds = [ln for ln in user.splitlines() if ln.strip().startswith("round ")]
        if not rounds:                              # tit-for-tat opens kindly
            return "I cooperate."
        return "I defect." if "they defected" in rounds[-1] else "I cooperate."

    return FakeChat(answer)


def judge():
    raw = FoldJudge(lambda f: "cooperate" in f["text"].lower(), id="move@1")
    return Validated(raw, Validation(tier=Tier.FOLD, verdict=Verdict.PASSED,
                                     cases=40, discrimination=1.0, note="probed"))


def arena(journal=None):
    return Tournament(PEOPLE, responder=Responder(chat(), journal=journal),
                      rounds=4, journal=journal)


def test_a_tournament_needs_an_opponent():
    with pytest.raises(ValueError, match="at least two agents"):
        Tournament(PEOPLE[:1], responder=Responder(chat()))


def test_every_pair_meets_and_every_move_is_judged():
    a = arena()
    rulings = a.run({}, judge())
    assert len(rulings) == 3 * 4 * 2          # 3 pairings x 4 rounds x 2 players
    assert all({"agent", "round", "cooperated", "payoff"} <= set(r.facts)
               for r in rulings)


def test_tit_for_tat_opens_kindly_then_retaliates():
    """The behaviour the classic result turns on, read off the journal rather
    than assumed."""
    a = arena()
    a.run({}, judge())
    assert a.scores["c"].rate == 1.0          # the cooperator never defects
    assert a.scores["d"].rate == 0.0
    assert 0.0 < a.scores["t"].rate < 1.0     # kind first, then not


def test_the_defector_wins_under_the_classic_payoffs():
    a = arena()
    a.run({}, judge())
    assert a.scores["d"].points > a.scores["c"].points


def test_the_payoff_matrix_is_read_from_the_config():
    """Sweeping the temptation payoff sweeps the incentive, exactly as fitness
    does in Evolution — the arena holds no private copy of the reward."""
    a = arena()
    a.run({"temptation": 5.0}, judge())
    greedy = a.scores["d"].points
    b = arena()
    b.run({"temptation": 0.5}, judge())       # defecting no longer pays
    assert b.scores["d"].points < greedy


def test_pairings_and_scores_are_journalled(tmp_path):
    path = tmp_path / "t.jsonl"
    with Journal(path, Provenance(served="fake")) as j:
        arena(journal=j).run({}, judge())
    lines = [json.loads(ln) for ln in path.read_text().splitlines()]
    pairings = [r for r in lines if r["t"] == "pairing"]
    final = [r for r in lines if r["t"] == "tournament"][-1]
    assert len(pairings) == 3
    assert final["c"]["cooperation_rate"] == 1.0


def test_sweeping_the_temptation_brackets_where_defection_stops_paying():
    holder = {}

    def cooperation(rulings):
        del rulings
        return holder["arena"].cooperation_rate()

    class Fresh:
        def run(self, config, j):
            holder["arena"] = arena()
            return holder["arena"].run(config, j)

    b = sweep(Fresh(), judge(), Coordinate("temptation", 0.0, 6.0),
              Outcome(cooperation, threshold=0.5, name="cooperation"),
              budget=Budget(runs=20), replicates=2)
    # Cooperation here is a property of the fixed genomes, not of the payoff, so
    # the honest answer is that no flip exists in this range — and the sweep says
    # so rather than bisecting noise into a boundary.
    assert b.verdict is Verdict.COULD_NOT_JUDGE
    assert "indistinguishable" in b.note
