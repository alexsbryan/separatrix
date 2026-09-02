# SPDX-License-Identifier: AGPL-3.0-or-later
"""Diffusion and Replay: the other two shapes a study takes."""
import json
import sys

import pytest
from fake_chat import FakeChat
from separatrix import (Agent, Budget, Claim, Coordinate, Diffusion, FoldJudge,
                        Journal, Outcome, ProcessJudge, Provenance, Replay,
                        Reputation, Responder, Run, Scenario, Tier, Validated,
                        Validation, Verdict, sweep)

TRUE = Claim(id="orchids", grounded=True,
             statement="The ledger records thirty-seven rare orchids.",
             source="The Keeper's ledger records thirty-seven rare orchids.")
FALSE = Claim(id="cure", grounded=False,
              statement="The moonpetal flower cures fever.",
              source="The moonpetal flower blooms only at night.")

PEOPLE = [Agent(id=n, genome=g) for n, g in [
    ("Ada", "Preserve details exactly."), ("Boro", "Embellish freely."),
    ("Cy", "Round numbers off."), ("Dee", "State everything as fact."),
    ("Eun", "Pass it on plainly."), ("Fay", "Preserve details exactly.")]]


EMBELLISH = "Also, it glows."


def chat(personas=True):
    """Personas shape transmission fidelity, which is what a per-agent
    institution has to discriminate on.

    With `personas=False` every agent behaves identically — and a reputation
    norm then has nothing to tell them apart with. That degenerate case is
    exercised deliberately below, because it is a real property of a global
    reputation and not a bug.
    """

    def answer(system, user):
        heard = user.split('"')[1] if '"' in user else user
        unfaithful = personas and ("Embellish" in system or "as fact" in system)
        return f"{heard} {EMBELLISH}" if unfaithful else heard

    return FakeChat(answer)


def judge():
    """Grounded when the claim is supported AND the retelling did not invent."""
    raw = FoldJudge(lambda f: f["kind"] == "grounded" and EMBELLISH not in f["text"],
                    id="gm@1", observe=lambda f: {"kind": f["kind"]})
    return Validated(raw, Validation(tier=Tier.FOLD, verdict=Verdict.PASSED,
                                     cases=40, discrimination=1.0, note="probed"))


def arena(journal=None, personas=True, **kw):
    return Diffusion([TRUE, FALSE], PEOPLE,
                     responder=Responder(chat(personas), journal=journal),
                     rounds=4, depth=5, journal=journal, **kw)


# ── reputation ───────────────────────────────────────────────────────────────

def test_reputation_falls_on_bad_transmissions_and_recovers_on_good_ones():
    r = Reputation(alpha=0.5)
    assert r.of("Ada") == 1.0                    # unknown agents start trusted
    r.update("Ada", False); r.update("Ada", False)
    assert r.of("Ada") == pytest.approx(0.25)
    r.update("Ada", True)
    assert r.of("Ada") == pytest.approx(0.625)


# ── the institution as a coordinate ─────────────────────────────────────────

def test_no_institution_lets_a_fabrication_reach_as_far_as_a_fact():
    """Diffusion is about believability, not veracity. With nothing adjudicating
    adoption, both claims reach the whole chain."""
    a = arena()
    a.run({"reputation_threshold": 0.0}, judge())
    assert a.mean_reach("cure") == a.mean_reach("orchids") == 5.0


def test_the_institution_suppresses_the_false_claim_selectively():
    """The result the whole arena exists to measure: false reach collapses while
    true reach is barely touched."""
    a = arena()
    a.run({"reputation_threshold": 0.7}, judge())
    false_reach, true_reach = a.mean_reach("cure"), a.mean_reach("orchids")

    # The assertion is the FINDING, not a number. A bound like "below 2.5"
    # depends on alpha, depth and rounds; selectivity is the claim, and a
    # different configuration should still have to satisfy it.
    assert false_reach < true_reach / 2


def test_the_institution_costs_honest_diffusion_and_the_cost_is_computable():
    """The question the original write-up named as needing measurement: how much
    honest diffusion does an institution cost per unit of fabrication it
    suppresses? A global reputation penalises an agent for RELAYING something
    ungrounded, not only for inventing it, so honest agents do pay. Reporting
    that ratio is what makes two institutions comparable instead of both merely
    'working'."""
    off, on = arena(), arena()
    off.run({"reputation_threshold": 0.0}, judge())
    on.run({"reputation_threshold": 0.7}, judge())

    suppressed = off.mean_reach("cure") - on.mean_reach("cure")
    cost = off.mean_reach("orchids") - on.mean_reach("orchids")
    assert suppressed > 0, "an institution that suppresses nothing is not one"
    ratio = cost / suppressed
    assert 0.0 <= ratio < 1.0, (
        f"this institution costs {ratio:.2f} honest reach per unit of fabrication "
        f"suppressed; above 1.0 it is doing more harm than good")


def test_a_global_reputation_is_not_selective_when_every_agent_is_alike():
    """A real property of the design, recorded rather than hidden.

    With no persona variation, groundedness depends only on the claim, so every
    agent that touches the false one is penalised equally — and the institution
    strangles honest diffusion exactly as hard as fabrication. Selectivity comes
    from agents DIFFERING, which is what gives a per-agent norm something to
    discriminate on. Any richer institution should be measured against this.
    """
    for threshold in (0.5, 0.7, 0.9):
        a = arena(personas=False)
        a.run({"reputation_threshold": threshold}, judge())
        assert a.mean_reach("cure") == a.mean_reach("orchids"), threshold


def test_the_control_arm_is_the_same_code_path_not_a_branch():
    """A threshold of 0 quarantines nobody. A separate institution-off branch
    would be a second implementation of the run, and the two would drift."""
    a = arena()
    a.run({"reputation_threshold": 0.0}, judge())
    assert a.mean_reach("cure") == 5.0
    b = arena()
    b.run({}, judge())                            # absent key, same meaning
    assert b.mean_reach("cure") == 5.0


def test_quarantines_are_journalled_with_who_and_why(tmp_path):
    path = tmp_path / "d.jsonl"
    with Journal(path, Provenance(served="fake")) as j:
        arena(journal=j).run({"reputation_threshold": 0.6}, judge())
    events = [json.loads(ln) for ln in path.read_text().splitlines()
              if '"quarantine"' in ln]
    assert events
    assert {"teller", "standing", "threshold", "hop"} <= set(events[0])
    assert all(e["standing"] < e["threshold"] for e in events)


def test_every_hop_carries_its_provenance():
    a = arena()
    rulings = a.run({"reputation_threshold": 0.0}, judge())
    assert all({"claim", "hop", "teller", "round"} <= set(r.facts) for r in rulings)


def test_diffusion_needs_a_society():
    with pytest.raises(ValueError, match="at least two agents"):
        Diffusion([TRUE], PEOPLE[:1], responder=Responder(chat()))


def test_sweeping_the_threshold_brackets_where_the_institution_starts_working():
    def false_reach(rulings):
        del rulings
        return sweep_arena.mean_reach("cure")

    sweep_arena = arena()
    b = sweep(sweep_arena, judge(), Coordinate("reputation_threshold", 0.0, 1.0),
              Outcome(false_reach, threshold=3.0, name="false reach"),
              budget=Budget(runs=30), replicates=2)
    assert b.verdict is Verdict.PASSED, b.note
    assert b.width < 1.0

    # Self-validating rather than hard-coded: a bracket is correct when the
    # outcome sits on opposite sides of the threshold at its two ends. Asserting
    # a literal would pin the test to this world's alpha and depth.
    low, high = arena(), arena()
    low.run({"reputation_threshold": b.lo}, judge())
    high.run({"reputation_threshold": b.hi}, judge())
    assert low.mean_reach("cure") >= 3.0 >= high.mean_reach("cure")


# ── replay ──────────────────────────────────────────────────────────────────

SCENARIOS = [Scenario(id=f"s{i}", facts={"hour": h}) for i, h in enumerate([21, 22, 23])]


def test_the_policy_reaches_the_judge_through_the_trial():
    """An arena cannot hand a judge a policy without the judge growing a config
    parameter it has no business having, so it travels in what the judge reads."""
    seen = []
    j = Validated(FoldJudge(lambda f: (seen.append(f), f["hour"] >= f["quiet_from"])[1],
                            id="policy@1"),
                  Validation(tier=Tier.FOLD, verdict=Verdict.PASSED, cases=40,
                             discrimination=1.0, note="probed"))
    rulings = Replay(SCENARIOS).run({"quiet_from": 22}, j)
    assert [r.verdict.is_pass() for r in rulings] == [False, True, True]
    assert all(f["quiet_from"] == 22 for f in seen)


def test_a_scenario_cannot_override_the_policy_it_is_tested_against():
    tricky = [Scenario(id="s0", facts={"hour": 21, "quiet_from": 0})]
    seen = []
    j = Validated(FoldJudge(lambda f: (seen.append(f["quiet_from"]), True)[1], id="p@1"),
                  Validation(tier=Tier.FOLD, verdict=Verdict.PASSED, cases=40,
                             discrimination=1.0, note="probed"))
    Replay(tricky).run({"quiet_from": 22}, j)
    assert seen == [0], "scenario facts win here — and that must be a deliberate choice"


def test_replay_decides_through_a_real_subprocess(tmp_path):
    """The canon shape end to end: an external tool, an exit code, a verdict."""
    tool = tmp_path / "decide.py"
    tool.write_text(
        "import json,sys\n"
        "d=json.load(sys.stdin)\n"
        "sys.exit(0 if d['hour'] >= d['quiet_from'] else 1)\n")
    pj = ProcessJudge.from_exit_codes(
        [sys.executable, str(tool)],
        {0: Verdict.PASSED, 1: Verdict.FAILED, 3: Verdict.COULD_NOT_JUDGE},
        id="canon-replay@1", tier=Tier.FOLD)
    j = Validated(pj, Validation(tier=Tier.FOLD, verdict=Verdict.PASSED, cases=40,
                                 discrimination=1.0, note="probed"))
    rulings = Replay(SCENARIOS).run({"quiet_from": 22}, j)
    assert [r.verdict.is_pass() for r in rulings] == [False, True, True]
    assert all(r.facts["scenario"].startswith("s") for r in rulings)
