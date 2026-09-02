# SPDX-License-Identifier: AGPL-3.0-or-later
"""A fixed scenario set, decided under a policy. No population, no model.

The governance shape, and the one `canon replay` already occupies: given a body
of scenarios that actually happened and a candidate policy, what would that
policy have decided? The arena supplies the scenarios; the judge — usually a
`ProcessJudge` wrapping the real tool — supplies the decision as a pure fold.

**The config reaches the judge through the trial.** An arena cannot hand a judge
a policy directly without the judge growing a config parameter it has no business
having, so the policy travels as part of what the judge reads. A `ProcessJudge`
sends those facts on stdin, and the wrapper turns them into whatever flags the
tool wants.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ..journal import Journal
from ..judge import Judge
from ..trial import Trial, digest
from ..verdict import Ruling

__all__ = ["Scenario", "Replay"]


@dataclass(frozen=True)
class Scenario:
    """One thing that happened, and whatever a policy needs to decide about it."""

    id: str
    facts: Mapping[str, Any]


@dataclass(frozen=True)
class _Configured(Trial):
    """A scenario carrying the config it is being decided under."""

    scenario: Scenario
    config: Mapping[str, Any]

    @property
    def id(self) -> str:
        return digest("configured", self.scenario.id, dict(self.config))

    def facts(self) -> Mapping[str, Any]:
        # config first, so a scenario can never quietly override the policy it
        # is being tested against.
        return {**dict(self.config), **dict(self.scenario.facts),
                "scenario": self.scenario.id}


Scenarios = Sequence[Scenario] | Callable[[Mapping[str, Any]], Sequence[Scenario]]


class Replay:
    """Decide every scenario under one configuration."""

    def __init__(self, scenarios: Scenarios, *, journal: Journal | None = None):
        self._scenarios = scenarios
        self.journal = journal

    def scenarios(self, config: Mapping[str, Any]) -> Sequence[Scenario]:
        return self._scenarios(config) if callable(self._scenarios) else self._scenarios

    def draw(self, label: str) -> None:
        """Nothing here is cached between draws — a scenario is data already in hand — so a
        replicate is already independent and there is nothing to separate.

        Declared rather than omitted: a sweep warns about an arena that cannot
        say, because the silent case is one whose replicates share state and
        nobody noticed."""

    def run(self, config: Mapping[str, Any], judge: Judge) -> Sequence[Ruling]:
        rulings: list[Ruling] = []
        for scenario in self.scenarios(config):
            ruling = judge.rule(_Configured(scenario, config))
            rulings.append(Ruling(
                verdict=ruling.verdict, trial_id=ruling.trial_id, judge=ruling.judge,
                note=ruling.note,
                facts={**dict(ruling.facts), "scenario": scenario.id}))
            if self.journal:
                self.journal.note("decision", scenario=scenario.id,
                                  verdict=ruling.verdict.value, note=ruling.note,
                                  **{k: v for k, v in config.items()})
        return rulings
