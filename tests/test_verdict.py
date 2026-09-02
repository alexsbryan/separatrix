# SPDX-License-Identifier: AGPL-3.0-or-later
"""Four verdicts, and the one rule that makes them worth having."""
from separatrix import Ruling, Verdict


def test_only_passed_is_a_pass():
    assert Verdict.PASSED.is_pass()
    for v in (Verdict.FAILED, Verdict.COULD_NOT_JUDGE, Verdict.NEVER_RAN):
        assert not v.is_pass(), v


def test_could_not_judge_never_rescues_a_failure():
    """The rule the whole enum exists for. An unjudgeable axis beside a failed
    one does not soften it, average with it, or outvote it."""
    assert Verdict.combine([Verdict.FAILED, Verdict.COULD_NOT_JUDGE]) is Verdict.FAILED
    assert Verdict.combine([Verdict.COULD_NOT_JUDGE, Verdict.FAILED]) is Verdict.FAILED
    assert Verdict.combine([Verdict.PASSED, Verdict.PASSED, Verdict.FAILED]) is Verdict.FAILED


def test_an_absent_verdict_is_never_a_pass():
    assert Verdict.combine([Verdict.PASSED, Verdict.COULD_NOT_JUDGE]) is Verdict.COULD_NOT_JUDGE
    assert Verdict.combine([Verdict.PASSED, Verdict.NEVER_RAN]) is Verdict.NEVER_RAN


def test_nothing_ran_so_nothing_passed():
    assert Verdict.combine([]) is Verdict.NEVER_RAN


def test_all_passed_is_a_pass():
    assert Verdict.combine([Verdict.PASSED] * 5) is Verdict.PASSED


def test_judged_distinguishes_answered_from_absent():
    assert Verdict.PASSED.is_judged() and Verdict.FAILED.is_judged()
    assert not Verdict.COULD_NOT_JUDGE.is_judged()
    assert not Verdict.NEVER_RAN.is_judged()


def test_a_ruling_carries_the_instrument_that_produced_it():
    r = Ruling(verdict=Verdict.PASSED, trial_id="t1", judge="fold@2", facts={"declined": True})
    row = r.as_row()
    assert row["judge"] == "fold@2" and row["verdict"] == "passed"
    assert row["facts"] == {"declined": True}
