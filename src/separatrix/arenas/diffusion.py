# SPDX-License-Identifier: AGPL-3.0-or-later
"""A claim propagates through a society, and something adjudicates it.

The telephone game with a referee. Each agent retells **what it heard**, not the
source, so drift compounds; the judge scores every retelling against the
*original* source, so the question "did this launder into fabrication" has an
answer rather than an opinion.

The institution is the swept coordinate. A reputation norm keeps an exponential
average of how grounded each teller's past transmissions were and refuses
adoption below a threshold — so sweeping that threshold sweeps *how much
institution* the society has, and the bracket says where it starts working.

**The control arm is not a special case.** A threshold of 0 quarantines nobody,
which is the no-institution condition, reached by the same code path as every
other value. A separate "institution off" branch would be a second
implementation of the run, and the two would drift.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..agent import Agent, Responder
from ..journal import Journal
from ..judge import Judge
from ..trial import Exchange, Response, Situation
from ..verdict import Ruling

__all__ = ["Claim", "Diffusion"]

RETELL = "You heard: \"{heard}\"\n\nPass this along to someone else, in your own words."


@dataclass(frozen=True)
class Claim:
    """Something to propagate, and the source it is answerable to."""

    id: str
    statement: str
    source: str
    grounded: bool                # whether the source actually supports it


@dataclass
class Reputation:
    """How grounded each teller's transmissions have been. EMA, so a fabricator
    loses standing quickly and an honest agent recovers it."""

    alpha: float = 0.4
    initial: float = 1.0
    scores: dict[str, float] = field(default_factory=dict)

    def of(self, agent_id: str) -> float:
        return self.scores.get(agent_id, self.initial)

    def update(self, agent_id: str, grounded: bool) -> float:
        prior = self.of(agent_id)
        self.scores[agent_id] = (1 - self.alpha) * prior + self.alpha * float(grounded)
        return self.scores[agent_id]


class Diffusion:
    """Chains of retellings, judged hop by hop, with an institution that can
    break a chain."""

    def __init__(
        self,
        claims: Sequence[Claim],
        population: Sequence[Agent],
        *,
        responder: Responder,
        rounds: int = 5,
        depth: int = 5,
        journal: Journal | None = None,
        seed: int = 7,
    ):
        if len(population) < 2:
            raise ValueError("diffusion needs at least two agents")
        self.claims = list(claims)
        self.population = list(population)
        self.responder = responder
        self.rounds, self.depth = rounds, depth
        self.journal = journal
        self.seed = seed
        self.reach: dict[str, list[int]] = {}      # per round: who CARRIED the claim
        self.spoke: dict[str, list[int]] = {}      # per round: who spoke at all

    def draw(self, label: str) -> None:
        """Begin a new draw. Every replicate is a fresh one, so nothing this
        arena cached for another replicate is reused as if it were a new
        answer."""
        self.responder.separate(label)

    def run(self, config: Mapping[str, Any], judge: Judge) -> Sequence[Ruling]:
        threshold = float(config.get("reputation_threshold", 0.0))
        rng = random.Random(self.seed)
        reputation = Reputation()
        rulings: list[Ruling] = []
        self.reach = {c.id: [] for c in self.claims}
        self.spoke = {c.id: [] for c in self.claims}

        for rnd in range(self.rounds):
            for claim in self.claims:
                chain = rng.sample(self.population, min(self.depth, len(self.population)))
                heard, adopters, carriers = claim.statement, set(), set()

                for hop, teller in enumerate(chain):
                    standing = reputation.of(teller.id)
                    if standing < threshold:
                        # The institution acting: the chain dies here.
                        if self.journal:
                            self.journal.note("quarantine", round=rnd, claim=claim.id,
                                              hop=hop, teller=teller.id,
                                              standing=round(standing, 4),
                                              threshold=threshold)
                        break

                    situation = Situation(
                        prompt=RETELL.format(heard=heard), evidence=(claim.source,),
                        kind="grounded" if claim.grounded else "ungrounded",
                        meta={"claim": claim.id, "hop": hop})
                    response = self.responder(teller, situation)
                    ruling = judge.rule(Exchange(situation, response))
                    grounded = ruling.verdict.is_pass()

                    rulings.append(Ruling(
                        verdict=ruling.verdict, trial_id=ruling.trial_id,
                        judge=ruling.judge, note=ruling.note,
                        facts={**dict(ruling.facts), "claim": claim.id, "hop": hop,
                               "teller": teller.id, "round": rnd,
                               "claim_grounded": claim.grounded,
                               "rounds": self.rounds,
                               "standing": round(standing, 4)}))
                    reputation.update(teller.id, grounded)
                    adopters.add(teller.id)
                    # The claim TRAVELLED only if the retelling still asserts it:
                    # a grounded claim carried faithfully (the judge passes it),
                    # an ungrounded one relayed unsupported (the judge fails it).
                    # A teller who refuses, or who replaces the rumour with what
                    # the source actually says, is not reach — A9 established that
                    # for the swept outcome and this is the same rule, in the one
                    # place that now decides it. PREREGISTRATION.md A16.
                    if grounded == claim.grounded:
                        carriers.add(teller.id)
                    heard = response.text          # the next agent hears the DRIFT

                    if self.journal:
                        self.journal.note("hop", round=rnd, claim=claim.id, hop=hop,
                                          teller=teller.id, grounded=grounded,
                                          verdict=ruling.verdict.value,
                                          statement=heard[:400])

                self.reach[claim.id].append(len(carriers))
                self.spoke[claim.id].append(len(adopters))

        if self.journal:
            self.journal.note("reach", threshold=threshold,
                              per_claim={c: rounds for c, rounds in self.reach.items()},
                              mean={c: (sum(v) / len(v) if v else 0.0)
                                    for c, v in self.reach.items()},
                              spoke={c: (sum(v) / len(v) if v else 0.0)
                                     for c, v in self.spoke.items()},
                              reputation=dict(sorted(reputation.scores.items())))
        return rulings

    # ── what a sweep measures ───────────────────────────────────────────────

    def mean_reach(self, claim_id: str) -> float:
        """Per-round mean of how many tellers CARRIED the claim.

        Until A16 this counted `adopters` — everyone who spoke, refusals and
        corrections included — while the swept outcome counted only spreaders.
        Two quantities, one name, and they disagreed: 5.0 and 6.0 for the same
        world. `FINDINGS.md`'s cost-ratio table was built on the speaker count,
        which credits the institution for silencing tellers who were not
        spreading anything. Who spoke is still recorded, under `spoke`, because
        it is a real number — it is just not reach.
        """
        rounds = self.reach.get(claim_id) or []
        return sum(rounds) / len(rounds) if rounds else float("nan")
