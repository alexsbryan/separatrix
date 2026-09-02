# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Mesa model as an arena.

**Built on `Model.step`, `Model.running` and
`DataCollector.get_model_vars_dataframe()`, never on `batch_run`.** Mesa is
mid-major-transition and `batch_run` does not survive it: 3.5.1 ships
`mesa/batchrunner.py` and exports `batch_run`, while `main` — self-reporting
`4.0.0a0` — has no `batchrunner.py`, no `batch_run` in `__all__`, and zero
code-search hits for it. The three names above exist in both, so an adapter
resting on them spans the major version.

Nothing here imports mesa. The surface is small enough to duck-type, which means
this works with any Mesa version, with a subclass, or with something that merely
looks like one — and core keeps its zero dependencies. Pandas is converted away
at the boundary: a `Run` carries rows, never a DataFrame.

**`batch_run` when a step is free; a sweep when a step costs a second.** On a
single axis with cheap samples a full factorial is simpler and fine. The reason
to be here is that your agents call a model, and Mesa has no way to score what
one *said* — nor any notion of whether the thing scoring it is biased toward the
parameter you are varying.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..journal import Journal
from ..judge import Judge
from ..trial import Trial, digest
from ..verdict import Ruling, Verdict

__all__ = ["TrajectoryTrial", "MesaArena", "rows_of"]

REQUIRED = ("step", "running", "datacollector")


@dataclass(frozen=True)
class TrajectoryTrial(Trial):
    """The `(config, trajectory)` shape: a whole run, judged as one thing."""

    rows: tuple[Mapping[str, Any], ...]
    config: Mapping[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return digest("trajectory", [dict(r) for r in self.rows], dict(self.config))

    def facts(self) -> Mapping[str, Any]:
        return {**dict(self.config), "rows": [dict(r) for r in self.rows],
                "steps": len(self.rows),
                "final": dict(self.rows[-1]) if self.rows else {}}


def rows_of(frame: Any) -> list[dict]:
    """A DataFrame, or anything already row-shaped, as plain dicts.

    Converting here is what keeps pandas out of core: everything downstream —
    the journal, the cache, the fold — sees ordinary JSON-able rows.
    """
    if hasattr(frame, "to_dict"):
        return list(frame.to_dict("records"))
    return [dict(r) for r in frame]


class MesaArena:
    """Run a Mesa model once per configuration and judge what it produced."""

    def __init__(
        self,
        model_cls: Callable[..., Any],
        *,
        steps: int,
        trial_from: Callable[[list[dict], Mapping[str, Any]], Iterable[Trial]] | None = None,
        journal: Journal | None = None,
        **fixed: Any,
    ):
        self.model_cls = model_cls
        self.steps = steps
        # A trajectory with no rows is not a trial. Wrapping zero rows in a
        # TrajectoryTrial hands the judge an empty object to rule on, and
        # whatever it says about nothing becomes a verdict about the run.
        self.trial_from = trial_from or (
            lambda rows, config: [TrajectoryTrial(tuple(rows), config)] if rows else [])
        self.journal = journal
        self.fixed = fixed

    def run(self, config: Mapping[str, Any], judge: Judge) -> Sequence[Ruling]:
        model = self.model_cls(**{**self.fixed, **dict(config)})
        missing = [name for name in REQUIRED if not hasattr(model, name)]
        if missing:
            raise TypeError(
                f"{type(model).__name__} is missing {', '.join(missing)} — this adapter "
                f"needs only Model.step, Model.running and Model.datacollector"
                f".get_model_vars_dataframe(), which is the surface Mesa 3.5 and 4.0 "
                f"share. It deliberately does not use batch_run, which 4.0 removes.")

        taken = 0
        for _ in range(self.steps):
            if not model.running:
                break
            model.step()
            taken += 1

        rows = rows_of(model.datacollector.get_model_vars_dataframe())
        if self.journal:
            self.journal.note("simulation", model=type(model).__name__,
                              steps_taken=taken, steps_asked=self.steps,
                              rows=len(rows), **{k: v for k, v in config.items()})

        trials = list(self.trial_from(rows, dict(config)))
        if not trials:
            # A model that collected nothing did not run a trial, and an empty
            # pass is a green result nobody earned.
            return [Ruling(verdict=Verdict.COULD_NOT_JUDGE,
                           trial_id=digest("empty", dict(config)), judge=judge.id,
                           note=f"the model produced no rows in {taken} steps")]
        return [judge.rule(t) for t in trials]
