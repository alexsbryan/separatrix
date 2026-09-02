# SPDX-License-Identifier: AGPL-3.0-or-later
"""Selection on natural-language strategies.

The arena that makes the library's thesis executable. **Fitness is a function of
the config**, and the config is what a sweep varies — so sweeping a coordinate
sweeps the *incentive*, and the bracket that comes back says where the reward
structure stops producing one disposition and starts producing another.

What is measured is the FINAL generation. Earlier generations are journalled in
full, including each one's champion genome, because the champion is the finding:
a rate tells you selection moved, and the sentence tells you what it moved
toward.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ..agent import Agent, Responder
from ..journal import Journal
from ..judge import Judge
from ..trial import Exchange, Situation
from ..verdict import Ruling

__all__ = ["Evolution", "llm_rewrite"]

World = Sequence[Situation] | Callable[[Mapping[str, Any]], Sequence[Situation]]
Fitness = Callable[[Sequence[Ruling], Mapping[str, Any]], float]
Mutate = Callable[[str, Mapping[str, Any]], str]

REWRITE_SYSTEM = "You write concise, effective strategies. Output ONLY the strategy."
REWRITE_USER = (
    "An agent follows this strategy:\n\n\"{parent}\"\n\n"
    "Rewrite it to do better at its task. Keep it GENERAL — describe the shape of "
    "the behaviour, never a specific question, topic, or fact. 1-3 sentences. "
    "Output only the new strategy.")


def llm_rewrite(responder: Responder, *, temperature: float = 0.9) -> Mutate:
    """Mutation as a rewrite. The model authors the variation; selection keeps it.

    Deliberately blind to the fitness function: an author told what scores well
    optimises the metric directly, and what you learn then is what the metric
    rewards on paper rather than what the reward structure breeds.
    """

    def mutate(parent: str, config: Mapping[str, Any]) -> str:
        completion = responder.chat.complete(
            REWRITE_SYSTEM, REWRITE_USER.format(parent=parent),
            temperature=temperature, max_tokens=220)
        responder._witness(completion.served)
        return completion.text.strip() or parent

    return mutate


@dataclass
class Generation:
    index: int
    scored: list[tuple[float, Agent, list[Ruling]]]

    @property
    def champion(self) -> tuple[float, Agent, list[Ruling]]:
        return self.scored[0]


class Evolution:
    """A population of strategy texts under a reward structure."""

    def __init__(
        self,
        world: World,
        seeds: Sequence[str],
        *,
        responder: Responder,
        fitness: Fitness,
        mutate: Mutate | None = None,
        generations: int = 4,
        survivors: int = 2,
        journal: Journal | None = None,
    ):
        if not seeds:
            raise ValueError("a population needs at least one seed strategy")
        if survivors < 1:
            raise ValueError("survivors must be at least 1")
        self._world = world
        self.seeds = list(seeds)
        self.responder = responder
        self.fitness = fitness
        self.mutate = mutate or llm_rewrite(responder)
        self.generations = generations
        self.survivors = min(survivors, len(seeds))
        self.journal = journal
        self.history: list[Generation] = []

    def situations(self, config: Mapping[str, Any]) -> Sequence[Situation]:
        return self._world(config) if callable(self._world) else self._world

    def draw(self, label: str) -> None:
        """Begin a new draw. Every replicate is a fresh one, so nothing this
        arena cached for another replicate is reused as if it were a new
        answer."""
        self.responder.separate(label)

    def run(self, config: Mapping[str, Any], judge: Judge) -> Sequence[Ruling]:
        situations = self.situations(config)
        population = [Agent(id=f"a{i}", genome=g) for i, g in enumerate(self.seeds)]
        self.history = []
        final: list[Ruling] = []

        for gen in range(self.generations):
            scored: list[tuple[float, Agent, list[Ruling]]] = []
            for agent in population:
                rulings = [judge.rule(Exchange(s, self.responder(agent, s)))
                           for s in situations]
                scored.append((self.fitness(rulings, config), agent, rulings))
            scored.sort(key=lambda row: row[0], reverse=True)
            self.history.append(Generation(gen, scored))
            self._journal_generation(gen, scored, config)

            final = [r for _, _, rs in scored for r in rs]
            if gen < self.generations - 1:
                population = self._reproduce(scored, gen + 1, config)

        return final

    # ── reproduction ────────────────────────────────────────────────────────

    def _reproduce(self, scored, generation: int, config) -> list[Agent]:
        """Keep the best, refill the rest by mutating them round-robin.

        Population size is constant, so a generation's cost is knowable in
        advance — which is what lets the sweep forecast before it spends.
        """
        size = len(scored)
        survivors = [agent for _, agent, _ in scored[: self.survivors]]
        offspring: list[Agent] = []
        while len(survivors) + len(offspring) < size:
            parent = survivors[len(offspring) % len(survivors)]
            offspring.append(Agent(id=f"g{generation}c{len(offspring)}",
                                   genome=self.mutate(parent.genome, config),
                                   born=generation, parent=parent.id))
        return survivors + offspring

    # ── glassbox ────────────────────────────────────────────────────────────

    def _journal_generation(self, gen: int, scored, config) -> None:
        if not self.journal:
            return
        fit, champ, rulings = scored[0]
        counts: dict[str, int] = {}
        for r in rulings:
            counts[r.verdict.value] = counts.get(r.verdict.value, 0) + 1
        self.journal.note(
            "generation", gen=gen, population=len(scored),
            fitness={a.id: round(f, 4) for f, a, _ in scored},
            champion_id=champ.id, champion_fitness=round(fit, 4),
            # The sentence IS the finding. A rate says selection moved; this says
            # what it moved toward, and it is the part a reader can argue with.
            champion_genome=champ.genome, champion_counts=counts,
            cache_hits=self.responder.hits, cache_misses=self.responder.misses)
