# SPDX-License-Identifier: AGPL-3.0-or-later
"""Agents whose genome is a sentence, and the thing that makes them speak.

A genome here is natural-language strategy text, so mutation is a rewrite and
selection acts on dispositions rather than parameters. That is the whole reason
these populations are worth simulating: what gets selected is legible, and the
champion can be read.

`Responder` is the only path from an agent to a model. It owns the cache, so
re-sweeping one coordinate reuses every sample the change did not touch — within
one DRAW, never across two, for the reason set out on `key` — and it watches
what the endpoint actually served — because an endpoint that starts
serving a different model mid-study has invalidated the comparison, and that
must be visible rather than averaged in.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

from .client import UNREPORTED, Chat, Completion
from .journal import Journal, response_key
from .trial import Response, Situation

__all__ = ["Agent", "Responder", "DEFAULT_SYSTEM"]

DEFAULT_SYSTEM = "{genome}"


@dataclass(frozen=True)
class Agent:
    """An identity and a strategy. The identity is stable so reputation, memory
    and lineage can attach to it across generations."""

    id: str
    genome: str
    born: int = 0                      # the generation it entered in
    parent: str | None = None
    memory: tuple[str, ...] = ()

    def descendant(self, genome: str, generation: int) -> "Agent":
        return replace(self, genome=genome, born=generation, parent=self.id, memory=())

    def remembering(self, *items: str) -> "Agent":
        return replace(self, memory=self.memory + tuple(items))


class Responder:
    """(agent, situation) -> Response, through a model, a cache, and a journal."""

    def __init__(self, chat: Chat, *, cache: Mapping[str, str] | None = None,
                 journal: Journal | None = None, system: str = DEFAULT_SYSTEM,
                 render: Callable[[Situation, Agent], str] | None = None,
                 draw: str = "", workers: int = 1):
        self.chat = chat
        self.draw = str(draw)
        self.workers = max(1, int(workers))
        self._lock = threading.Lock()
        self.cache: dict[str, str] = dict(cache or {})
        self.finishes: dict[str, str] = {}
        self.journal = journal
        self.system = system
        self.render = render or (lambda s, a: s.prompt if not s.evidence else
                                 "\n".join([*[f"- {e}" for e in s.evidence], "", s.prompt]))
        self.served: set[str] = set()
        self.hits = self.misses = self.truncated = 0

    def key(self, agent: Agent, situation: Situation) -> str:
        """Everything that would change the answer, and nothing that would not.

        The agent's *id* is deliberately absent: two agents holding the same
        genome asked the same question are the same call, and paying twice for
        it at these sample costs is money set on fire.

        The DRAW is present, and it is the field this class got wrong first. A
        cache that spans replicates hands the second replicate the first one's
        answers, so what was recorded as three draws is one draw and two copies
        — and the noise estimated from them is smaller than the sampler's, which
        makes a boundary look resolvable when it is not. Sampling noise is the
        thing this library exists to respect, so it does not get to be a cache
        hit. See `Responder.separate`.
        """
        return response_key(genome=agent.genome, situation=situation.id,
                            model=self.chat.model, system=self.system,
                            temperature=self.chat.temperature,
                            max_tokens=self.chat.max_tokens, draw=self.draw)

    def separate(self, draw: str) -> None:
        """Begin a new draw. Answers cached under a different one are not reused.

        Partitioning rather than clearing, because a repeated label SHOULD hit:
        that is what lets a sweep pay once for the parts of two coordinate
        values that are identical, while keeping the replicates at each value
        independent of each other.
        """
        self.draw = str(draw)

    def __call__(self, agent: Agent, situation: Situation) -> Response:
        key = self.key(agent, situation)
        with self._lock:
            cached = self.cache.get(key)
            if cached is not None:
                self.hits += 1
        if cached is not None:
            return Response(text=cached, by=agent.id, situation_id=situation.id,
                            meta={"cached": True,
                                  "finish": self.finishes.get(key, "")})

        with self._lock:
            self.misses += 1
        completion: Completion = self.chat.complete(
            self.system.format(genome=agent.genome), self.render(situation, agent))
        with self._lock:
            self._witness(completion.served)
            self.cache[key] = completion.text
            self.finishes[key] = completion.finish
            if completion.cut_off:
                self.truncated += 1
            if self.journal:
                self.journal.response(key, completion.text, served=completion.served,
                                      by=agent.id, situation=situation.id,
                                      finish=completion.finish)
        return Response(text=completion.text, by=agent.id, situation_id=situation.id,
                        meta={"served": completion.served, "finish": completion.finish})

    def many(self, pairs: Sequence[tuple[Agent, Situation]]) -> list[Response]:
        """Answer several independent questions, in the order they were asked.

        The agents within one generation do not talk to each other, so nothing
        about them is sequential except the network. `workers` is therefore a
        wall-clock setting and nothing else, and the test that says so is
        `test_agent.py::test_workers_change_the_wall_clock_and_nothing_else`.

        Distinct KEYS are dispatched, not distinct pairs: two agents holding the
        same genome asked the same question are one call whether the loop is
        serial or not, so the cache counts come out the same either way. Without
        that, concurrency would quietly buy duplicate calls and call them misses.
        """
        pairs = list(pairs)
        if self.workers == 1 or len(pairs) < 2:
            return [self(agent, situation) for agent, situation in pairs]

        first: dict[str, int] = {}
        for i, (agent, situation) in enumerate(pairs):
            first.setdefault(self.key(agent, situation), i)

        answers: dict[int, Response] = {}
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(self, *pairs[i]): i for i in first.values()}
            for future in as_completed(futures):
                answers[futures[future]] = future.result()

        # The rest read what the first of their key just cached, so ordering and
        # hit counts match the serial path exactly.
        return [answers[i] if (i := first[self.key(agent, situation)]) == n
                else self(agent, situation)
                for n, (agent, situation) in enumerate(pairs)]

    def _witness(self, served: str) -> None:
        """Record what answered.

        Normalising here and not only inside `Chat` is deliberate: the rule is
        that a journal never carries an alias where a served id belongs, and a
        rule that holds in one client implementation is not a rule. Any client
        satisfying the protocol gets the same guarantee.
        """
        served = (served or "").strip() or UNREPORTED
        if served in self.served:
            return
        if self.served and self.journal:
            # Not a warning to be read later: a comparison that spans two models
            # is not the comparison anyone thinks they ran.
            self.journal.note("model_changed", was=sorted(self.served), now=served)
        self.served.add(served)

    @property
    def provenance_served(self) -> str:
        """What to record. Names every model if the endpoint changed under us."""
        if not self.served:
            return "(no call was made)"
        return " + ".join(sorted(self.served))
