# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bisect toward the flip, and admit what the noise would not let you resolve.

The one job. A control-parameter range goes in; where the population's fate
flips comes out, as a bracket with the noise band that set its resolution.

**Why not a grid.** An LLM-driven run is `agents x interactions` sequential
calls, orders of magnitude more expensive per sample than a rule-based one. A
factorial spends its samples uniformly across a range that is mostly flat.
Bisection spends them at the boundary. The two also produce different objects: a
factorial gives a response surface, this gives a boundary with a stated
resolution — and an admission of what it could not resolve.

**The noise floor sets the resolution, and the result says so.** Bisecting a
stochastic outcome below its own noise is measuring the sampler, not the system.
So noise is measured first, from replicates at fixed points, and the search stops
when the midpoint can no longer be told from the threshold. You never get a
point. You get an interval and the reason it is that wide.

**Replicates are repeats, not seeds.** Where sampling happens server-side the
client cannot seed it, so a "replicate" varies the draw and does not control it.
That is what makes the noise real and worth measuring rather than an artifact to
be configured away.

**And a repeat that reuses the last one's answers is not a repeat.** The first
version of this file shared one response cache across every replicate, so half
of each sample was a copy of the sample before it and the noise floor came out
smaller than the sampler's. Replicates are separated by `draw_label` now, and an
arena that cannot say whether it separates them is warned about rather than
trusted.
"""
from __future__ import annotations

import math
import statistics
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from .judge import Judge
from .journal import Journal
from .verdict import Ruling, Verdict

__all__ = ["Coordinate", "Outcome", "Budget", "Forecast", "Bracket", "Arena",
           "Search", "sweep", "bracket_from_records", "draw_label"]

#: The fraction of its own range a bracket must reach to count as a located
#: boundary. A study overrides it with `[sweep] resolve_to`. A quarter is where
#: §A14 already set the bar in prose when it registered what R2 had to beat;
#: §A15 made it the rule and gave it a home in the study file.
DEFAULT_RESOLVE_TO = 0.25



class Arena(Protocol):
    """Produces judged trials for one configuration. The expensive half."""

    def run(self, config: Mapping[str, Any], judge: Judge) -> Sequence[Ruling]:
        ...

    def draw(self, label: str) -> None:
        """Begin a new draw, discarding nothing but reusing nothing either.

        An arena that caches model answers MUST partition them by this label,
        or its replicates are one draw copied — see `Responder.key`. An arena
        with nothing cached implements it empty and says so; what it must not
        do is leave the question unanswered, which is why `sweep` warns about
        an arena that does not have this method at all.
        """


@dataclass(frozen=True)
class Coordinate:
    """The axis being swept, and how a value reaches the arena's config."""

    name: str
    lo: float
    hi: float

    def __post_init__(self) -> None:
        if not self.hi > self.lo:
            raise ValueError(f"coordinate {self.name!r}: hi must exceed lo")

    @property
    def span(self) -> float:
        return self.hi - self.lo

    def at(self, config: Mapping[str, Any], value: float) -> dict:
        return {**dict(config), self.name: value}


@dataclass(frozen=True)
class Outcome:
    """Rulings collapsed to one number, and the line it has to cross."""

    measure: Callable[[Sequence[Ruling]], float]
    threshold: float
    name: str = "outcome"

    @staticmethod
    def pass_rate(rulings: Sequence[Ruling]) -> float:
        """The default measure: judged trials that passed. Unjudged trials are
        excluded from the denominator rather than counted as failures — they are
        absent evidence, not evidence of absence."""
        judged = [r for r in rulings if r.verdict.is_judged()]
        if not judged:
            return float("nan")
        return sum(r.verdict.is_pass() for r in judged) / len(judged)


@dataclass(frozen=True)
class Budget:
    """What the sweep may spend, counted in arena runs."""

    runs: int
    per_run_calls: int | None = None      # for the forecast only

    def forecast(self, replicates: int, span: float) -> "Forecast":
        floor_cost = 2 * replicates
        steps = max(0, (self.runs - floor_cost) // max(1, replicates))
        return Forecast(runs=min(self.runs, floor_cost + steps * replicates),
                        steps=steps, replicates=replicates,
                        final_width=span / (2 ** steps) if steps else span,
                        calls=None if self.per_run_calls is None
                        else (floor_cost + steps * replicates) * self.per_run_calls)


@dataclass(frozen=True)
class Forecast:
    """What this sweep will cost, before it spends anything."""

    runs: int
    steps: int
    replicates: int
    final_width: float
    calls: int | None = None

    def render(self, coord: Coordinate) -> str:
        cost = f"{self.runs} runs" + (f" / ~{self.calls} model calls" if self.calls else "")
        if self.steps == 0:
            return (f"{cost}: enough to measure noise at both ends of {coord.name}, "
                    f"and NOTHING left to bisect with. Raise the budget or lower "
                    f"replicates.")
        return (f"{cost}: noise from {self.replicates} replicates at each end, then "
                f"{self.steps} bisection steps on {coord.name} "
                f"[{coord.lo:g}, {coord.hi:g}] -> final bracket ~{self.final_width:g} "
                f"wide, if noise does not stop it sooner.")


@dataclass(frozen=True)
class Bracket:
    """Where the flip is, how wide, and why not narrower."""

    verdict: Verdict
    coordinate: str
    lo: float
    hi: float
    noise: float | None = None
    threshold: float | None = None
    samples: int = 0
    ends: Mapping[str, float] = field(default_factory=dict)
    note: str = ""
    resolve_to: float | None = None      # the bar this bracket had to reach

    @property
    def width(self) -> float:
        return self.hi - self.lo

    def render(self) -> str:
        head = f"{self.verdict}  {self.coordinate}"
        if self.verdict is not Verdict.PASSED:
            return f"{head}\n  {self.note}"
        bar = ("" if self.resolve_to is None
               else f", inside the {self.resolve_to:g} of range this study asked for")
        return (f"{head} flips in [{self.lo:g}, {self.hi:g}]  (width {self.width:g}"
                f"{bar})\n"
                f"  noise {self.noise:.4g} at threshold {self.threshold:g}; "
                f"{self.samples} runs\n  {self.note}")

    def as_row(self) -> dict:
        return {"verdict": self.verdict.value, "coordinate": self.coordinate,
                "lo": self.lo, "hi": self.hi, "width": self.width, "noise": self.noise,
                "threshold": self.threshold, "samples": self.samples,
                "ends": dict(self.ends), "note": self.note,
                "resolve_to": self.resolve_to}


def _within_group_sd(*groups: Sequence[float]) -> float:
    """Pooled WITHIN-group spread — the sampler's own variability.

    Pooling across groups with different means would measure the effect and call
    it noise, which makes every real boundary look unresolvable. The groups here
    are replicates at one coordinate value, so their spread is the thing that
    limits resolution.
    """
    n = sum(len(g) for g in groups)
    if n <= len(groups):
        return 0.0
    ss = sum((x - statistics.fmean(g)) ** 2 for g in groups if g for x in g)
    return math.sqrt(ss / n)


def _se(noise: float, replicates: int) -> float:
    """Standard error of a mean of `replicates` draws."""
    return noise / math.sqrt(replicates)


def draw_label(value: float, rep: int, *, paired: bool) -> str:
    """Which draw a sample belongs to. One decider for the whole library.

    Replicates at one coordinate value ALWAYS get different labels: that is the
    correctness half, and the noise floor is estimated from exactly that spread.

    Across values the default is to REPEAT the label — common random numbers.
    The parts of two configurations that are identical (a seed population, a
    first generation) are then paid for once and answered identically, which
    sharpens the comparison between values without touching the within-value
    spread the resolution is derived from. `paired=False` buys full
    independence instead, at the cost of re-paying for every shared part.
    """
    return f"rep{rep}" if paired else f"{value:g}#rep{rep}"


def _absent(verdict: Verdict, coord: Coordinate, note: str, **kw) -> Bracket:
    return Bracket(verdict=verdict, coordinate=coord.name, lo=coord.lo, hi=coord.hi,
                   note=note, **kw)


class Search:
    """The decider, and the only one.

    Bisection has to make its choice DURING acquisition — the next value depends
    on the last measurement — so the decision cannot be a fold applied at the
    end. It is a state machine instead, and the same one is driven twice: by
    `sweep`, which pays for each sample, and by `bracket_from_records`, which
    replays samples off a journal for free.

    Two drivers, one decider. A second implementation of this rule would be a
    second answer to "where is the boundary", and the journal would stop being
    able to speak for the run.
    """

    def __init__(self, coordinate: Coordinate, outcome: Outcome, replicates: int,
                 max_runs: int | None = None, resolve_to: float = DEFAULT_RESOLVE_TO):
        self.coord, self.outcome = coordinate, outcome
        self.replicates, self.max_runs = replicates, max_runs
        if not 0 < resolve_to <= 1:
            raise ValueError(f"resolve_to must be in (0, 1], got {resolve_to!r}: it is "
                             f"the FRACTION of its own range a bracket must reach to "
                             f"count as located")
        self.resolve_to = resolve_to
        self.lo, self.hi = coordinate.lo, coordinate.hi
        self.spent = 0
        self.noise: float | None = None
        self.resolution = 0.0
        self.means: dict[float, float] = {}
        self._lo_vals: list[float] = []
        self._hi_vals: list[float] = []
        self._above_hi = True
        self._done: Bracket | None = None
        self._stopped = ""

    # ── what to sample next ─────────────────────────────────────────────────

    def next(self) -> float | None:
        if self._done is not None:
            return None
        if not self._lo_vals:
            return self.coord.lo
        if not self._hi_vals:
            return self.coord.hi
        if self.max_runs is not None and self.spent + self.replicates > self.max_runs:
            self._finish(f"budget exhausted after {self.spent} runs; the bracket is as "
                         f"narrow as {self.max_runs} runs at {self.replicates} "
                         f"replicates allows")
            return None
        return (self.lo + self.hi) / 2

    # ── what came back ──────────────────────────────────────────────────────

    def observe(self, value: float, ys: Sequence[float]) -> None:
        self.spent += len(ys)
        if any(y != y for y in ys):
            self._finish("the outcome is undefined at an endpoint — no trial was "
                         "judged there, so there is nothing to bisect between.",
                         verdict=Verdict.COULD_NOT_JUDGE)
            return
        mean = statistics.fmean(ys)
        self.means[value] = mean

        if not self._lo_vals:
            self._lo_vals = list(ys)
            return
        if not self._hi_vals:
            self._hi_vals = list(ys)
            self._settle_ends()
            return

        # A zero noise floor cannot stop a search. With no sampling uncertainty
        # there is nothing to be unresolvable about, and treating an outcome that
        # lands exactly ON the threshold as ambiguous returns the whole range —
        # which is what a deterministic study with a discrete outcome does every
        # time. Resolution has to be positive to be a floor.
        if self.resolution > 0 and abs(mean - self.outcome.threshold) <= self.resolution:
            self._finish(
                f"stopped at the noise floor: {self.outcome.name} {mean:.3g} at "
                f"{value:g} is within {self.resolution:.3g} of the threshold "
                f"(per-sample noise {self.noise:.3g} over {self.replicates} "
                f"replicates), so which side it falls on is not resolvable with "
                f"these samples")
            return
        if (mean > self.outcome.threshold) == self._above_hi:
            self.hi = value
        else:
            self.lo = value

    def _settle_ends(self) -> None:
        self.noise = _within_group_sd(self._lo_vals, self._hi_vals)
        self.resolution = 2 * _se(self.noise, self.replicates)
        mean_lo = statistics.fmean(self._lo_vals)
        mean_hi = statistics.fmean(self._hi_vals)
        gap_needed = 2 * _se(self.noise, self.replicates) * math.sqrt(2)

        if abs(mean_hi - mean_lo) <= gap_needed:
            self._finish(
                f"the ends are indistinguishable: {self.outcome.name} {mean_lo:.3g} vs "
                f"{mean_hi:.3g}, a gap smaller than the {gap_needed:.3g} this many "
                f"replicates can resolve (per-sample noise {self.noise:.3g}). Widen the "
                f"range or raise replicates.", verdict=Verdict.COULD_NOT_JUDGE)
            return
        self._above_hi = mean_hi > self.outcome.threshold
        if (mean_lo > self.outcome.threshold) == self._above_hi:
            self._finish(
                f"no flip in range: both ends sit on the same side of "
                f"{self.outcome.threshold:g} ({mean_lo:.3g}, {mean_hi:.3g}). The "
                f"boundary, if there is one, is outside [{self.coord.lo:g}, "
                f"{self.coord.hi:g}].", verdict=Verdict.FAILED)

    # ── the answer ──────────────────────────────────────────────────────────

    def _finish(self, note: str, verdict: Verdict = Verdict.PASSED) -> None:
        # A PASSED that did not localise anything is not a resolved boundary.
        # The noise-floor branch calls this without a verdict and can fire on
        # ANY step, including the first — the midpoint lands within the
        # resolution of the threshold, the search halts, and whatever bisection
        # happened to be holding is handed back wearing the word PASSED. Both
        # halves are true and only one was being said: the ends do straddle, so
        # a flip IS in there, and a bracket that is most of its own range has
        # located nothing.
        #
        # A13 caught only the extreme of that — a bracket still spanning the
        # FULL range — and the floor turned out to sit exactly one bisection
        # step too low. A14's R3 returned width 0.5 of a range of 1 and passed;
        # R2 halted at the same noise floor one step earlier and was refused.
        # Two runs, one stopping cause, two different verdicts, decided by an
        # off-by-one in when the floor fired. PREREGISTRATION.md A15.
        #
        # So the bar is a FRACTION OF THE RANGE, and it is declared per study in
        # `[sweep] resolve_to` rather than chosen here as a constant — the same
        # move §A8 and §A11 made for thresholds, and for the same reason: a bar
        # somebody registers before a run is worth more than one the library
        # picked afterwards.
        if verdict is Verdict.PASSED and self.hi - self.lo > self.resolve_to * self.coord.span:
            verdict = Verdict.COULD_NOT_JUDGE
            reached = ("the search stopped before narrowing that at all, so this "
                       "locates nothing"
                       if self.lo <= self.coord.lo and self.hi >= self.coord.hi else
                       f"the search reached [{self.lo:g}, {self.hi:g}], which is "
                       f"{(self.hi - self.lo) / self.coord.span:.0%} of the range and "
                       f"wider than the {self.resolve_to:.0%} this study asked for")
            note = (f"the ends straddle {self.outcome.threshold:g}, so a flip is "
                    f"somewhere in [{self.coord.lo:g}, {self.coord.hi:g}] — but "
                    f"{reached}. {note}")
        keep_span = verdict is not Verdict.PASSED
        self._done = Bracket(
            verdict=verdict, coordinate=self.coord.name,
            lo=self.coord.lo if keep_span else self.lo,
            hi=self.coord.hi if keep_span else self.hi,
            noise=self.noise, threshold=self.outcome.threshold, samples=self.spent,
            resolve_to=self.resolve_to,
            ends={f"{self.coord.lo:g}": statistics.fmean(self._lo_vals) if self._lo_vals else float("nan"),
                  f"{self.coord.hi:g}": statistics.fmean(self._hi_vals) if self._hi_vals else float("nan")},
            note=note)

    def result(self) -> Bracket:
        if self._done is None:
            # A REPLAY has no budget — it has however many samples the journal
            # holds — and saying "as narrow as None runs allows" prints an
            # absence as if it were a count, which is the one thing this library
            # is not allowed to do.
            self._finish(
                f"budget exhausted after {self.spent} runs; the bracket is as narrow "
                f"as {self.max_runs} runs at {self.replicates} replicates allows"
                if self.max_runs is not None else
                f"the journal holds no further samples; the bracket is as narrow as "
                f"its {self.spent} recorded runs at {self.replicates} replicates allow")
        return self._done


def sweep(
    arena: Arena,
    judge: Judge,
    coordinate: Coordinate,
    outcome: Outcome,
    *,
    budget: Budget,
    replicates: int = 5,
    paired: bool = True,
    resolve_to: float = DEFAULT_RESOLVE_TO,
    config: Mapping[str, Any] | None = None,
    journal: Journal | None = None,
    on_forecast: Callable[[Forecast], None] | None = None,
) -> Bracket:
    """Find where `outcome` crosses its threshold along `coordinate`.

    The driver that pays. It acquires samples and hands them to `Search`, which
    decides everything.
    """
    config = dict(config or {})

    validation = judge.validation()
    if not validation.usable():
        return _absent(Verdict.COULD_NOT_JUDGE, coordinate,
                       f"judge {judge.id} is not usable: {validation.verdict} — "
                       f"{validation.note}. Probe it first.")
    if replicates < 2:
        return _absent(Verdict.COULD_NOT_JUDGE, coordinate,
                       "replicates < 2: one run is not a measurement, and noise "
                       "cannot be estimated from a single draw.")

    forecast = budget.forecast(replicates, coordinate.span)
    if on_forecast:
        on_forecast(forecast)
    if journal:
        journal.note("forecast", coordinate=coordinate.name, runs=forecast.runs,
                     steps=forecast.steps, replicates=replicates,
                     final_width=forecast.final_width)
    if budget.runs < 2 * replicates:
        return _absent(Verdict.NEVER_RAN, coordinate,
                       f"budget of {budget.runs} runs cannot even measure noise, which "
                       f"needs {2 * replicates}. Nothing was spent.")

    separates = callable(getattr(arena, "draw", None))
    if journal:
        journal.note("draws", separated=separates, paired=paired,
                     arena=type(arena).__name__)
    if not separates:
        # Not an error — an arena with nothing cached is entitled to replicates
        # that are already independent. But it did not say so, and the case that
        # looks identical from here is an arena serving its first replicate's
        # answers to the next two. Absence is reported, never assumed benign.
        warnings.warn(
            f"{type(arena).__name__} has no draw(label) method, so this sweep "
            f"cannot separate replicates. If it caches model answers, its "
            f"replicates are one draw copied and the noise floor below is not "
            f"the sampler's.", RuntimeWarning, stacklevel=2)

    search = Search(coordinate, outcome, replicates, max_runs=budget.runs,
                    resolve_to=resolve_to)
    while (value := search.next()) is not None:
        ys = []
        for rep in range(replicates):
            label = draw_label(value, rep, paired=paired)
            if separates:
                arena.draw(label)
            rulings = arena.run(coordinate.at(config, value), judge)
            y = outcome.measure(rulings)
            ys.append(y)
            if journal:
                journal.note("sample", coordinate=coordinate.name, value=value,
                             rep=rep, draw=label if separates else None,
                             outcome=y, name=outcome.name, rulings=len(rulings))
        search.observe(value, ys)

    bracket = search.result()
    if journal:
        journal.note("bracket", **bracket.as_row())
    return bracket


def bracket_from_records(records: Iterable[Mapping[str, Any]], *, threshold: float,
                         name: str = "outcome",
                         resolve_to: float = DEFAULT_RESOLVE_TO) -> Bracket:
    """Re-derive a bracket from journalled samples. No model, no endpoint.

    The driver that pays nothing. It replays recorded samples through the same
    `Search`, so a published bracket can be checked against the evidence that
    produced it by anyone holding the journal.
    """
    # A sweep restarted inside one run leaves two sets of samples in the same
    # journal, and folding both would re-derive a search nobody performed. The
    # forecast record is written once per sweep, so it marks where the live one
    # began.
    records = list(records)
    last_start = max((i for i, r in enumerate(records)
                      if r.get("t") == "forecast"), default=-1)
    samples: list[dict] = [r for r in records[last_start + 1:]
                           if r.get("t") == "sample"]
    if not samples:
        raise ValueError("no sample records in this journal — nothing to re-derive")

    # The measure already ran when the samples were taken; re-deriving needs
    # only the line they had to cross.
    outcome = Outcome(measure=lambda rs: float("nan"), threshold=threshold, name=name)
    coord_name = samples[0].get("coordinate", "?")
    groups: list[tuple[float, list[float]]] = []
    for s in samples:
        value = float(s["value"])
        if not groups or groups[-1][0] != value:
            groups.append((value, []))
        groups[-1][1].append(float(s["outcome"]))

    values = [v for v, _ in groups]
    coord = Coordinate(coord_name, min(values), max(values))
    replicates = len(groups[0][1])
    search = Search(coord, outcome, replicates, resolve_to=resolve_to)
    for value, ys in groups:
        if search.next() is None:
            break
        search.observe(value, ys)
    return search.result()
