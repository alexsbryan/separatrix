# SPDX-License-Identifier: AGPL-3.0-or-later
"""Agents playing each other, not answering a world.

The Axelrod shape, which the other arenas cannot express: what an agent faces is
what another agent just did. Every pair meets for a fixed number of rounds, each
move is a response to the history so far, and the payoff matrix — the thing that
decides whether cooperating is worth it — is read from the **config**, so
sweeping it sweeps the incentive exactly as `Evolution` does with fitness.

The judge rules on each move, which is deliberate: whether a move was cooperative
is a reading of text, and a study should be free to disagree with the naive
keyword version of that reading. The payoff arithmetic then runs on the judge's
verdicts rather than on a second, private interpretation of the same replies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Mapping, Sequence

from ..agent import Agent, Responder
from ..journal import Journal
from ..judge import Judge
from ..trial import Exchange, Situation
from ..verdict import Ruling

__all__ = ["Tournament"]

FIRST = "You are meeting someone for the first time. Do you cooperate or defect?"
LATER = ("History with this partner (most recent last):\n{history}\n\n"
         "Do you cooperate or defect?")

# Classic prisoner's-dilemma payoffs; every one of them is overridable by config.
DEFAULT_PAYOFFS = {"reward": 3.0, "temptation": 5.0, "sucker": 0.0, "punishment": 1.0}


@dataclass
class Score:
    points: float = 0.0
    moves: int = 0
    cooperations: int = 0

    @property
    def rate(self) -> float:
        return self.cooperations / self.moves if self.moves else float("nan")


class Tournament:
    """Round-robin iterated play. Fitness is the payoff, not an opinion."""

    def __init__(self, population: Sequence[Agent], *, responder: Responder,
                 rounds: int = 4, journal: Journal | None = None):
        if len(population) < 2:
            raise ValueError("a tournament needs at least two agents")
        self.population = list(population)
        self.responder = responder
        self.rounds = rounds
        self.journal = journal
        self.scores: dict[str, Score] = {}

    def payoff(self, config: Mapping[str, Any], mine: bool, theirs: bool) -> float:
        p = {**DEFAULT_PAYOFFS, **{k: float(v) for k, v in config.items()
                                   if k in DEFAULT_PAYOFFS}}
        if mine and theirs:
            return p["reward"]
        if mine and not theirs:
            return p["sucker"]
        if not mine and theirs:
            return p["temptation"]
        return p["punishment"]

    def run(self, config: Mapping[str, Any], judge: Judge) -> Sequence[Ruling]:
        self.scores = {a.id: Score() for a in self.population}
        rulings: list[Ruling] = []

        for a, b in combinations(self.population, 2):
            history: list[tuple[bool, bool]] = []
            for rnd in range(self.rounds):
                moves, round_rulings = {}, {}
                for me, them in ((a, b), (b, a)):
                    situation = self._situation(history, me is a)
                    ruling = judge.rule(Exchange(situation, self.responder(me, situation)))
                    # A PASSED verdict means the judge read the move as cooperation.
                    moves[me.id] = ruling.verdict.is_pass()
                    round_rulings[me.id] = ruling

                mine, theirs = moves[a.id], moves[b.id]
                history.append((mine, theirs))
                for who, cooperated, other in ((a, mine, theirs), (b, theirs, mine)):
                    score = self.scores[who.id]
                    score.points += self.payoff(config, cooperated, other)
                    score.moves += 1
                    score.cooperations += cooperated
                    r = round_rulings[who.id]
                    rulings.append(Ruling(
                        verdict=r.verdict, trial_id=r.trial_id, judge=r.judge,
                        note=r.note,
                        facts={**dict(r.facts), "agent": who.id, "round": rnd,
                               "cooperated": cooperated, "partner_cooperated": other,
                               "payoff": self.payoff(config, cooperated, other)}))

            if self.journal:
                self.journal.note("pairing", a=a.id, b=b.id, rounds=self.rounds,
                                  history=[list(h) for h in history])

        if self.journal:
            self.journal.note("tournament", **{
                k: {"points": round(v.points, 3), "cooperation_rate": round(v.rate, 3)}
                for k, v in sorted(self.scores.items())})
        return rulings

    def _situation(self, history, is_first: bool) -> Situation:
        if not history:
            return Situation(prompt=FIRST, kind="opening")
        lines = [f"  round {i + 1}: you {'cooperated' if (m if is_first else t) else 'defected'}, "
                 f"they {'cooperated' if (t if is_first else m) else 'defected'}"
                 for i, (m, t) in enumerate(history)]
        return Situation(prompt=LATER.format(history="\n".join(lines)), kind="continuing")

    # ── what a sweep measures ───────────────────────────────────────────────

    def cooperation_rate(self) -> float:
        total = sum(s.moves for s in self.scores.values())
        return (sum(s.cooperations for s in self.scores.values()) / total
                if total else float("nan"))
