# SPDX-License-Identifier: AGPL-3.0-or-later
"""The two adapters: a simulator in another language, and a Mesa model."""
import json
import sys

import pytest
from separatrix import (Budget, Coordinate, FoldJudge, Journal, MesaArena, Outcome,
                        ProcessArena, Provenance, Tier, TrajectoryTrial, Validated,
                        Validation, Verdict, rows_of, sweep)


def _judge(decide, id="j@1"):
    return Validated(FoldJudge(decide, id=id),
                     Validation(tier=Tier.FOLD, verdict=Verdict.PASSED, cases=40,
                                discrimination=1.0, note="probed"))


def _py(script):
    return [sys.executable, "-c", script]


# ── ProcessArena: any simulator, any language ───────────────────────────────

EMIT = ("import json,sys\n"
        "c=json.load(sys.stdin)\n"
        "for i in range(3): print(json.dumps({'tick': i, 'harvest': c['rate']*i}))\n")


def test_a_foreign_simulator_becomes_judged_trials():
    arena = ProcessArena(_py(EMIT))
    rulings = arena.run({"rate": 2.0}, _judge(lambda f: f["harvest"] < 3))
    assert [r.verdict.is_pass() for r in rulings] == [True, True, False]


def test_the_config_reaches_the_simulator_and_the_judge():
    arena = ProcessArena(_py(EMIT))
    seen = []
    arena.run({"rate": 5.0}, _judge(lambda f: (seen.append(f), True)[1]))
    assert all(f["rate"] == 5.0 for f in seen)          # judge sees the config
    assert [f["harvest"] for f in seen] == [0.0, 5.0, 10.0]   # simulator did too


@pytest.mark.parametrize("script,fragment", [
    ("import sys; sys.stderr.write('boom'); sys.exit(3)", "exited 3"),
    ("print('not json')", "is not JSON"),
    ("print('[1,2]')", "is not an object"),
    ("pass", "produced no rows"),
    ("import time; time.sleep(30)", "timed out"),
])
def test_a_simulator_that_fails_never_fails_into_a_pass(script, fragment):
    """Including the quiet one: a simulator that emitted nothing did not run a
    trial, and reporting that as an empty pass is a green result nobody earned."""
    arena = ProcessArena(_py(script), timeout=0.5)
    rulings = arena.run({"rate": 1.0}, _judge(lambda f: True))
    assert [r.verdict for r in rulings] == [Verdict.COULD_NOT_JUDGE]
    assert fragment in rulings[0].note


def test_a_missing_simulator_is_reported_not_raised():
    rulings = ProcessArena(["separatrix-no-such-sim"]).run({}, _judge(lambda f: True))
    assert rulings[0].verdict is Verdict.COULD_NOT_JUDGE
    assert "could not run" in rulings[0].note


# ── MesaArena: the surface, and only the surface ────────────────────────────

class FakeCollector:
    def __init__(self):
        self.rows = []

    def collect(self, model):
        self.rows.append({"tick": model.ticks, "pool": model.pool})

    def get_model_vars_dataframe(self):
        return self.rows            # a real DataFrame would need .to_dict


class FakeModel:
    """Exactly the surface the adapter claims to need: step, running,
    datacollector. Nothing else, and no mesa import anywhere in this file."""

    def __init__(self, *, harvest=1.0, pool=10.0, regen=1.0):
        self.pool, self.harvest, self.regen = pool, harvest, regen
        self.ticks, self.running = 0, True
        self.datacollector = FakeCollector()

    def step(self):
        self.pool = max(0.0, self.pool - self.harvest + self.regen)
        self.ticks += 1
        self.datacollector.collect(self)
        if self.pool <= 0:
            self.running = False        # the commons collapsed


def test_a_mesa_shaped_model_runs_and_is_judged():
    arena = MesaArena(FakeModel, steps=5)
    rulings = arena.run({"harvest": 1.0}, _judge(lambda f: f["final"]["pool"] > 0))
    assert len(rulings) == 1 and rulings[0].verdict is Verdict.PASSED


def test_running_false_stops_the_model_early():
    """Mesa's own halting flag, honoured — a collapsed commons is not stepped on."""
    arena = MesaArena(FakeModel, steps=50)
    rulings = arena.run({"harvest": 5.0, "pool": 8.0},
                        _judge(lambda f: f["final"]["pool"] > 0))
    assert rulings[0].verdict is Verdict.FAILED
    assert rulings[0].trial_id


def test_the_adapter_names_exactly_what_it_needs_when_given_something_else():
    class NotAModel:
        def __init__(self, **kw):
            pass

    with pytest.raises(TypeError) as exc:
        MesaArena(NotAModel, steps=1).run({}, _judge(lambda f: True))
    message = str(exc.value)
    assert "step" in message and "running" in message and "datacollector" in message
    assert "batch_run" in message      # says why it is not used


def test_a_dataframe_is_converted_at_the_boundary():
    """Pandas never enters core: a Run carries rows, never a frame."""
    class Frame:
        def to_dict(self, orient):
            assert orient == "records"
            return [{"a": 1}, {"a": 2}]

    assert rows_of(Frame()) == [{"a": 1}, {"a": 2}]
    assert rows_of([{"a": 1}]) == [{"a": 1}]


def test_a_model_that_collected_nothing_is_could_not_judge():
    class Silent(FakeModel):
        def step(self):
            self.ticks += 1

    rulings = MesaArena(Silent, steps=3).run({}, _judge(lambda f: True))
    assert rulings[0].verdict is Verdict.COULD_NOT_JUDGE
    assert "no rows" in rulings[0].note


def test_per_step_trials_are_a_choice_the_caller_makes():
    """The default judges a whole trajectory. A study that wants per-step trials
    says so, and nothing in the adapter has to change."""
    from separatrix import RowTrial

    arena = MesaArena(FakeModel, steps=4,
                      trial_from=lambda rows, cfg: [RowTrial(r, cfg, i)
                                                    for i, r in enumerate(rows)])
    rulings = arena.run({"harvest": 1.0}, _judge(lambda f: f["pool"] > 0))
    assert len(rulings) == 4


def test_sweeping_a_mesa_model_brackets_its_collapse(tmp_path):
    """End to end through the adapter: where does harvesting tip the commons?"""
    path = tmp_path / "mesa.jsonl"
    with Journal(path, Provenance.modelless(), judge={"id": "j@1"}) as j:
        b = sweep(MesaArena(FakeModel, steps=20, journal=j, pool=10.0, regen=1.0),
                  _judge(lambda f: f["final"]["pool"] > 0),
                  Coordinate("harvest", 0.0, 4.0),
                  Outcome(Outcome.pass_rate, threshold=0.5, name="survives"),
                  budget=Budget(runs=40), replicates=2, journal=j)

    assert b.verdict is Verdict.PASSED, b.note
    assert json.loads(path.read_text().splitlines()[0])["t"] == "header"

    # The tipping point is arithmetic, not a guess: the pool drains by
    # (harvest - regen) per step, so 20 steps empty a pool of 10 once harvest
    # reaches regen + pool/steps = 1.0 + 0.5. Self-validated at both ends so the
    # test still holds if those numbers change.
    survives = MesaArena(FakeModel, steps=20, pool=10.0, regen=1.0)
    lo_run = survives.run({"harvest": b.lo}, _judge(lambda f: f["final"]["pool"] > 0))
    hi_run = survives.run({"harvest": b.hi}, _judge(lambda f: f["final"]["pool"] > 0))
    assert lo_run[0].verdict.is_pass() and not hi_run[0].verdict.is_pass()
