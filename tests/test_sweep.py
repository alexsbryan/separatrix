# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sweep: find the flip, or say honestly why you could not."""
import random

import pytest
from separatrix import (Bracket, Budget, Coordinate, FoldJudge, Journal, Outcome,
                        Provenance, Ruling, Run, Validated, Validation, Verdict, sweep)
from separatrix.judge import Tier
from separatrix.sweep import _within_group_sd

Y = Outcome(measure=lambda rs: rs[0].facts["y"], threshold=0.5, name="y")


class StepArena:
    """Outcome is `high` above the flip and `low` below it, plus jitter.

    Deterministic per seed, so a failing test is a real failure and not a draw.
    """

    def __init__(self, param="x", flip=0.5, low=0.2, high=0.9, jitter=0.0, seed=7):
        self.param, self.flip, self.low, self.high = param, flip, low, high
        self.jitter, self.rng, self.calls = jitter, random.Random(seed), 0

    def draw(self, label):
        """Nothing is cached here, so a replicate is already independent. Said
        out loud because a sweep does not assume it."""

    def run(self, config, judge):
        self.calls += 1
        base = self.high if config[self.param] > self.flip else self.low
        y = base + (self.rng.uniform(-self.jitter, self.jitter) if self.jitter else 0.0)
        return [Ruling(verdict=Verdict.PASSED, trial_id=f"t{self.calls}",
                       judge=judge.id, facts={"y": y})]


class RampArena(StepArena):
    """A transition with width, so the outcome passes THROUGH the threshold.

    A step function has no midpoint near the threshold, so bisection on one runs
    to budget and is right to. The noise floor only bites where the outcome
    changes continuously — which is what a real population does.
    """

    def __init__(self, crossing=0.37, base=0.2, threshold=0.5, jitter=0.05, seed=7):
        super().__init__(jitter=jitter, seed=seed)
        self.base, self.slope = base, (threshold - base) / crossing

    def run(self, config, judge):
        self.calls += 1
        y = self.base + self.slope * config[self.param]
        y += self.rng.uniform(-self.jitter, self.jitter) if self.jitter else 0.0
        return [Ruling(verdict=Verdict.PASSED, trial_id=f"t{self.calls}",
                       judge=judge.id, facts={"y": y})]


def _judge(usable=True):
    raw = FoldJudge(lambda f: True, id="fold@1")
    v = Validation(tier=Tier.FOLD,
                   verdict=Verdict.PASSED if usable else Verdict.NEVER_RAN,
                   cases=40, discrimination=1.0, note="probed" if usable else "never probed")
    return Validated(inner=raw, measured=v)


COORD = Coordinate("x", 0.0, 1.0)


# ── the gates that fire before anything is spent ─────────────────────────────

def test_an_unprobed_judge_stops_the_sweep_before_it_spends():
    arena = StepArena()
    b = sweep(arena, _judge(usable=False), COORD, Y, budget=Budget(runs=100))
    assert b.verdict is Verdict.COULD_NOT_JUDGE
    assert "not usable" in b.note and "Probe it first" in b.note
    assert arena.calls == 0          # nothing was spent on an instrument we distrust


def test_one_run_is_not_a_measurement():
    arena = StepArena()
    b = sweep(arena, _judge(), COORD, Y, budget=Budget(runs=100), replicates=1)
    assert b.verdict is Verdict.COULD_NOT_JUDGE
    assert "one run is not a measurement" in b.note
    assert arena.calls == 0


def test_a_budget_too_small_to_measure_noise_spends_nothing():
    arena = StepArena()
    b = sweep(arena, _judge(), COORD, Y, budget=Budget(runs=6), replicates=5)
    assert b.verdict is Verdict.NEVER_RAN
    assert "Nothing was spent" in b.note
    assert arena.calls == 0


# ── finding a boundary ───────────────────────────────────────────────────────

def test_a_clean_flip_is_bracketed_and_the_bracket_contains_it():
    arena = StepArena(flip=0.37)
    b = sweep(arena, _judge(), COORD, Y, budget=Budget(runs=60), replicates=3)
    assert b.verdict is Verdict.PASSED, b.note
    assert b.lo <= 0.37 <= b.hi
    assert b.width < COORD.span / 8          # actually narrowed it
    assert b.samples <= 60


def test_more_budget_buys_a_narrower_bracket():
    wide = sweep(StepArena(flip=0.37), _judge(), COORD, Y,
                 budget=Budget(runs=15), replicates=3)
    tight = sweep(StepArena(flip=0.37), _judge(), COORD, Y,
                  budget=Budget(runs=60), replicates=3)
    assert tight.width < wide.width
    assert "budget exhausted" in wide.note


def test_the_result_is_never_a_point():
    b = sweep(StepArena(flip=0.37), _judge(), COORD, Y,
              budget=Budget(runs=60), replicates=3)
    assert b.width > 0
    assert "flips in [" in b.render()


# ── the three ways it refuses to invent an answer ───────────────────────────

def test_noise_larger_than_the_effect_is_could_not_judge():
    """Swamp the step in jitter. There is a real boundary and this many samples
    cannot see it, so the sweep says that rather than bisecting noise."""
    arena = StepArena(flip=0.5, low=0.48, high=0.52, jitter=0.5)
    b = sweep(arena, _judge(), COORD, Y, budget=Budget(runs=60), replicates=3)
    assert b.verdict is Verdict.COULD_NOT_JUDGE
    assert "indistinguishable" in b.note
    assert "Widen the range or raise replicates" in b.note


def test_both_ends_on_the_same_side_is_a_definite_no():
    """A negative answer, not an absent one: the sweep looked and there is no
    crossing in this range."""
    arena = StepArena(low=0.8, high=0.9, flip=0.5)      # threshold 0.5 is below both
    b = sweep(arena, _judge(), COORD, Y, budget=Budget(runs=60), replicates=3)
    assert b.verdict is Verdict.FAILED
    assert "no flip in range" in b.note
    assert "outside" in b.note


def test_the_noise_floor_stops_the_bisection_and_says_so():
    """Enough jitter to separate the ends but not to place the midpoint. The
    bracket stops widening the claim rather than the interval."""
    arena = RampArena(crossing=0.37, jitter=0.05)
    b = sweep(arena, _judge(), COORD, Y, budget=Budget(runs=400), replicates=4)
    assert b.verdict is Verdict.PASSED, b.note
    assert "noise floor" in b.note
    assert b.samples < 400            # it stopped early rather than spending the budget
    assert b.lo <= 0.37 <= b.hi       # and the bracket still holds the true crossing


def test_a_sharp_step_is_right_to_bisect_to_budget():
    """The counterpart. A genuinely sharp boundary can be narrowed as far as the
    budget allows, because no midpoint ever sits ambiguously near the threshold."""
    b = sweep(StepArena(flip=0.37), _judge(), COORD, Y,
              budget=Budget(runs=60), replicates=3)
    assert "budget exhausted" in b.note
    assert b.lo <= 0.37 <= b.hi


def test_an_endpoint_nothing_judged_is_not_bisected_through():
    class Unjudged(StepArena):
        def run(self, config, judge):
            return [Ruling(verdict=Verdict.COULD_NOT_JUDGE, trial_id="t",
                           judge=judge.id, facts={"y": float("nan")})]

    b = sweep(Unjudged(), _judge(), COORD, Outcome(lambda rs: rs[0].facts["y"], 0.5),
              budget=Budget(runs=40), replicates=3)
    assert b.verdict is Verdict.COULD_NOT_JUDGE
    assert "undefined at an endpoint" in b.note


# ── the forecast, before anything is spent ──────────────────────────────────

def test_the_forecast_is_offered_before_the_first_run():
    seen, order = [], []
    arena = StepArena(flip=0.37)
    original = arena.run

    def spy(config, judge):
        order.append("run")
        return original(config, judge)

    arena.run = spy
    sweep(arena, _judge(), COORD, Y, budget=Budget(runs=30, per_run_calls=120),
          replicates=3, on_forecast=lambda f: (seen.append(f), order.append("forecast")))
    assert order[0] == "forecast"          # you are told the cost before paying it
    assert seen[0].steps == 8 and seen[0].calls == 30 * 120
    assert "model calls" in seen[0].render(COORD)


def test_a_budget_with_no_room_to_bisect_says_exactly_that():
    f = Budget(runs=10).forecast(replicates=5, span=1.0)
    assert f.steps == 0
    assert "NOTHING left to bisect" in f.render(COORD)


# ── the statistic the whole thing rests on ──────────────────────────────────

def test_noise_is_within_group_not_across_groups():
    """Pooling across two different means would measure the effect and call it
    noise, which makes every real boundary look unresolvable. This is the bug
    the first draft had."""
    lo, hi = [0.2, 0.2, 0.2], [0.9, 0.9, 0.9]
    assert _within_group_sd(lo, hi) == pytest.approx(0.0, abs=1e-12)
    assert _within_group_sd([0.1, 0.3], [0.8, 1.0]) == pytest.approx(0.1)


# ── journals: a bracket must be re-derivable like everything else ───────────

def test_every_sample_is_journalled_with_its_coordinate_value(tmp_path):
    path = tmp_path / "sweep.jsonl"
    prov = Provenance(served="Qwen3.6-35B-A3B", requested="primary")
    with Journal(path, prov, judge={"id": "fold@1"}) as j:
        b = sweep(StepArena(flip=0.37), _judge(), COORD, Y,
                  budget=Budget(runs=30), replicates=3, journal=j)

    run = Run.load(path)
    samples = [r for r in run.other if r["t"] == "sample"]
    forecasts = [r for r in run.other if r["t"] == "forecast"]
    assert len(forecasts) == 1
    assert len(samples) == b.samples
    assert {"value", "rep", "outcome", "coordinate"} <= set(samples[0])
    assert run.served == "Qwen3.6-35B-A3B"


# ── one decider, two drivers ─────────────────────────────────────────────────

def test_a_bracket_re_derives_from_its_own_journal_with_no_model(tmp_path, monkeypatch):
    """The charter's promise. A published bracket must be checkable by anyone
    holding the journal, without the thing that produced it."""
    import socket

    path = tmp_path / "sweep.jsonl"
    with Journal(path, Provenance(served="Qwen3.6-35B-A3B"), judge={"id": "fold@1"}) as j:
        live = sweep(StepArena(flip=0.37), _judge(), COORD, Y,
                     budget=Budget(runs=30), replicates=3, journal=j)

    def no_sockets(*a, **k):
        raise AssertionError("re-derivation opened a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)

    from separatrix import bracket_from_records
    again = bracket_from_records(Run.load(path).other, threshold=Y.threshold, name="y")

    assert again.verdict is live.verdict
    assert (again.lo, again.hi) == (live.lo, live.hi)
    assert again.samples == live.samples


def test_the_noise_limited_stop_re_derives_too(tmp_path):
    """The interesting one: replay has to reproduce the DECISION to stop, not
    just the arithmetic, or the two drivers have drifted."""
    from separatrix import bracket_from_records

    path = tmp_path / "ramp.jsonl"
    with Journal(path, Provenance(served="m")) as j:
        live = sweep(RampArena(crossing=0.37), _judge(), COORD, Y,
                     budget=Budget(runs=400), replicates=4, journal=j)
    again = bracket_from_records(Run.load(path).other, threshold=Y.threshold, name="y")
    assert "noise floor" in again.note
    assert (again.lo, again.hi) == (live.lo, live.hi)


def test_sep_bracket_confirms_the_recorded_result(tmp_path, capsys):
    from separatrix.__main__ import main as cli

    path = tmp_path / "sweep.jsonl"
    with Journal(path, Provenance(served="m")) as j:
        sweep(StepArena(flip=0.37), _judge(), COORD, Y,
              budget=Budget(runs=30), replicates=3, journal=j)

    code = cli(["bracket", str(path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "matches what was recorded" in out


def test_sep_bracket_reports_a_journal_that_contradicts_itself(tmp_path, capsys):
    """A recorded result its own evidence does not reproduce is the finding."""
    from separatrix.__main__ import main as cli

    path = tmp_path / "sweep.jsonl"
    with Journal(path, Provenance(served="m")) as j:
        sweep(StepArena(flip=0.37), _judge(), COORD, Y,
              budget=Budget(runs=30), replicates=3, journal=j)
    # someone edits the claim without touching the samples behind it
    lines = path.read_text().splitlines()
    lines = [ln.replace('"lo": 0.36', '"lo": 0.10') if '"t": "bracket"' in ln else ln
             for ln in lines]
    path.write_text("\n".join(lines) + "\n")

    code = cli(["bracket", str(path)])
    assert code == 2
    assert "MISMATCH" in capsys.readouterr().err


def test_a_zero_noise_floor_cannot_stop_the_search():
    """A deterministic arena has no sampling uncertainty, so nothing about it is
    unresolvable — including an outcome that lands exactly on the threshold.
    Treating that as ambiguous returns the whole range, which is what a discrete
    outcome does every time."""
    class Exact(StepArena):
        def run(self, config, judge):
            self.calls += 1
            # crosses the threshold exactly at x = 0.5
            return [Ruling(verdict=Verdict.PASSED, trial_id=f"t{self.calls}",
                           judge=judge.id, facts={"y": config[self.param]})]

    b = sweep(Exact(), _judge(), COORD, Outcome(lambda rs: rs[0].facts["y"], 0.5),
              budget=Budget(runs=30), replicates=2)
    assert b.verdict is Verdict.PASSED, b.note
    assert b.noise == 0.0
    assert b.width < COORD.span / 8       # it narrowed, rather than giving up
    assert b.lo <= 0.5 <= b.hi
