# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tier-ESTIMATED reference judge: a model reads, a fold decides.

This is the judge the library is actually for. Everything else here works when a
run's outcome can be computed; the case that needed a new tool is the one where
agents produce sentences and something has to read them, and the reader is the
part nobody can show you is fair.

**A model estimates a field. It does not return a verdict.** That is what
`Tier.ESTIMATED` says in words and it is worth having in the shape of the class,
because it puts the study's rule in one place with one implementation. The fold
judge and this one can then run the *same* rule over the same trials, differing
only in who read the reply — which makes "how much did the reader change the
answer" a number rather than an argument.

**The cache here is not the arena's cache, and the difference is the point.**
An arena's answers must not be reused across replicates: the arena is the
sampler, and its variability is the thing being measured (see `agent.py`). A
judge is the instrument, and an instrument that moves between two readings of
the same sentence is not measuring anything. So this asks at temperature 0 and
caches by content, deliberately and globally. Whether the reader is *actually*
stable is not assumed either — it is what a probe measures.

**Nothing fails into a pass.** An unparseable answer, an empty one, a call that
raised: all COULD_NOT_JUDGE, carrying the reason. A reader that could not read
is absent evidence, and absent evidence is never a verdict.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from ..client import Chat, ChatError
from ..journal import Journal, response_key
from ..judge import BaseJudge, Tier, cut_off
from ..trial import Trial
from ..verdict import Ruling, Verdict

__all__ = ["ChatJudge", "read_yes_no"]

SYSTEM = "You label replies. Answer with one word: YES or NO."
YES_NO = re.compile(r"\b(yes|no)\b", re.IGNORECASE)


def read_yes_no(text: str) -> bool | None:
    """The first plain yes or no in what came back, or None.

    None is a real answer here and must stay one. A reader that hedged, refused,
    or wandered off has not labelled the trial, and turning that into a NO would
    be a fabricated observation — the exact move that makes a judge's errors
    pile up on whichever arm provokes the hedging.
    """
    match = YES_NO.search(text or "")
    return None if match is None else match.group(1).lower() == "yes"


class ChatJudge(BaseJudge):
    """Asks a model one closed question per trial, then folds on the answer.

    `asks` is the question, in the fewest words that can carry it — this is a
    one-token classification and prose in the prompt buys nothing. `field` names
    where the answer lands in the trial's facts, and `decide` is the study's
    rule, which should be the *same* callable the fold judge uses.
    """

    def __init__(
        self,
        chat: Chat,
        *,
        id: str,
        asks: str,
        field: str,
        decide: Callable[[Mapping[str, Any]], Any],
        observe: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
        renders: Callable[[Mapping[str, Any]], str] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 256,
        tier: Tier = Tier.ESTIMATED,
        journal: Journal | None = None,
    ):
        super().__init__(id=id, tier=tier)
        self.chat = chat
        self.asks, self.field = asks, field
        self._decide, self._observe = decide, observe
        self._renders = renders or (lambda facts: str(facts.get("text", "")))
        # max_tokens is generous on purpose: a reasoning model emits a think
        # span before the word, and a budget sized for the word alone truncates
        # the answer away and turns every trial into COULD_NOT_JUDGE.
        self.temperature, self.max_tokens = temperature, max_tokens
        self.cache: dict[str, str] = {}
        self.journal = journal
        self.hits = self.misses = 0
        self.served: set[str] = set()

    def attach(self, journal: Journal) -> None:
        """Record every reading. A model judge that leaves no trace of what it
        read and what it said is not auditable, and its rulings are the only
        part of a sweep nobody can re-derive without it."""
        self.journal = journal

    # ── the reading ─────────────────────────────────────────────────────────

    def ask(self, facts: Mapping[str, Any]) -> tuple[bool | None, str]:
        """The estimate, and the reason when there is not one."""
        rendered = self._renders(facts)
        key = response_key(judge=self.id, asks=self.asks, rendered=rendered,
                           model=self.chat.model, temperature=self.temperature)
        if (cached := self.cache.get(key)) is not None:
            self.hits += 1
            answer = cached
        else:
            self.misses += 1
            try:
                completion = self.chat.complete(
                    SYSTEM, f"{self.asks}\n\nReply:\n{rendered}\n\nYES or NO:",
                    temperature=self.temperature, max_tokens=self.max_tokens)
            except ChatError as exc:
                return None, f"the reader could not be reached: {exc}"
            answer = completion.text
            self.cache[key] = answer
            self.served.add(completion.served)
            if self.journal:
                self.journal.response(key, answer, served=completion.served,
                                      by=self.id, situation=str(facts.get("kind", "")))

        estimate = read_yes_no(answer)
        if estimate is None:
            return None, f"the reader answered neither yes nor no: {answer[:120]!r}"
        return estimate, ""

    def rule(self, trial: Trial) -> Ruling:
        if cut_off(trial.facts()):
            return Ruling(verdict=Verdict.COULD_NOT_JUDGE, trial_id=trial.id,
                          judge=self.id,
                          note="the reply was cut off at the token limit, so it "
                               "neither answered nor declined")
        facts = dict(trial.facts())
        estimate, why = self.ask(facts)
        if estimate is None:
            return Ruling(verdict=Verdict.COULD_NOT_JUDGE, trial_id=trial.id,
                          judge=self.id, note=why)

        facts[self.field] = estimate
        try:
            decision = self._decide(facts)
        except Exception as exc:
            return Ruling(verdict=Verdict.COULD_NOT_JUDGE, trial_id=trial.id,
                          judge=self.id,
                          note=f"rule raised {type(exc).__name__}: {exc}")
        observed = dict(self._observe(facts)) if self._observe else {}
        if decision is None:
            return Ruling(verdict=Verdict.COULD_NOT_JUDGE, trial_id=trial.id,
                          judge=self.id, facts=observed, note="rule abstained")
        verdict = decision if isinstance(decision, Verdict) else (
            Verdict.PASSED if decision else Verdict.FAILED)
        return Ruling(verdict=verdict, trial_id=trial.id, judge=self.id, facts=observed)
