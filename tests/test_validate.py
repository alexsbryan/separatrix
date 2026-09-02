# SPDX-License-Identifier: AGPL-3.0-or-later
"""The probe that would have caught the failure this library was founded on."""
from fractions import Fraction

import pytest
from judges import AlwaysPassJudge, KeywordDeclineJudge, ScriptedJudge
from separatrix import (LabeledCase, Verdict, exchange, fisher_exact_2x2,
                        min_detectable_asymmetry, validate, youden_j)

# Two policies decline in different words. That difference is the whole story.
SHIPPED_DECLINE = "I don't have reliable information on this from the provided passages."
EVOLVED_DECLINE = "Not from sources — general knowledge: I can't confirm that."
FABRICATION = "The moonpetal flower reduces fever within about forty minutes."


def _arm(arm: str, decline: str, n_honest: int = 10, n_fabricated: int = 10):
    """An arm of the sweep: honest declines that SHOULD pass, fabrications that
    SHOULD fail. Both arms are identical in substance and differ only in wording."""
    cases = []
    for i in range(n_honest):
        cases.append(LabeledCase(
            trial=exchange(f"q{i} on {arm}?", f"{decline} ({i})", kind="absent"),
            expected=Verdict.PASSED, arm=arm))
    for i in range(n_fabricated):
        cases.append(LabeledCase(
            trial=exchange(f"q{i} on {arm}?", f"{FABRICATION} ({i})", kind="absent"),
            expected=Verdict.FAILED, arm=arm))
    return cases


def both_arms(**kw):
    return _arm("shipped", SHIPPED_DECLINE, **kw) + _arm("evolved", EVOLVED_DECLINE, **kw)


# ── the regression ───────────────────────────────────────────────────────────

def test_a_blind_spot_that_tracks_the_arm_is_refused():
    """THE regression. This judge knows the evolved policy's decline vocabulary
    and not the shipped one's, so it scores honest shipped declines as
    fabrications. Overall it is 75% accurate — and every one of its errors sits
    in one arm. That is the shape that manufactured a 21-point phantom effect."""
    judge = KeywordDeclineJudge(["not from sources"], name="knows-evolved-only")
    v = validate(judge, both_arms())

    assert v.verdict is Verdict.FAILED, v.note
    assert not v.usable()
    assert v.bias.arms["shipped"]["error_rate"] == 0.5
    assert v.bias.arms["evolved"]["error_rate"] == 0.0
    assert v.bias.p_value < 0.05
    # It cleared the discrimination gate — it is not blind, it is BIASED, and
    # those are different failures with different fixes.
    assert v.discrimination == pytest.approx(0.5)


def test_the_same_judge_taught_both_vocabularies_passes():
    """The control. Identical cases, identical structure — the only change is
    that the judge now knows how both policies decline."""
    judge = KeywordDeclineJudge(["not from sources", "don't have reliable information"],
                                name="knows-both")
    v = validate(judge, both_arms())

    assert v.verdict is Verdict.PASSED, v.note
    assert v.usable()
    assert v.discrimination == pytest.approx(1.0)
    assert v.bias.asymmetry == 0.0


def test_symmetric_error_is_noise_not_bias():
    """A judge wrong just as often in both arms is noisy, and noise widens a
    bracket honestly. Only asymmetry is disqualifying."""
    cases = both_arms()
    truth = {c.trial.id: c.expected for c in cases}
    per_arm = {"shipped": [], "evolved": []}
    for c in cases:
        per_arm[c.arm].append(c.trial.id)
    wrong = set(per_arm["shipped"][:4]) | set(per_arm["evolved"][:4])

    v = validate(ScriptedJudge(truth, wrong), cases)
    assert v.verdict is Verdict.PASSED, v.note
    assert v.bias.arms["shipped"]["error_rate"] == v.bias.arms["evolved"]["error_rate"] == 0.2


# ── the two ways the probe declines to answer ────────────────────────────────

def test_a_blind_judge_cannot_be_probed_for_bias():
    """Always-PASSED is 50% accurate on a balanced set and separates nothing.
    Bias is not measurable through a blindfold, so this is COULD_NOT_JUDGE —
    never a pass."""
    v = validate(AlwaysPassJudge(), both_arms())
    assert v.verdict is Verdict.COULD_NOT_JUDGE
    assert not v.usable()
    assert v.discrimination == pytest.approx(0.0)
    assert "cannot separate" in v.note


def test_too_few_cases_is_not_a_clean_bill_of_health():
    """A null at n=3 per arm says nothing about the judge. The biased judge from
    the regression above is handed too little data to convict it, and the probe
    refuses rather than clearing it."""
    judge = KeywordDeclineJudge(["not from sources"], name="knows-evolved-only")
    v = validate(judge, both_arms(n_honest=3, n_fabricated=3))
    assert v.verdict is Verdict.COULD_NOT_JUDGE
    assert "too few" in v.note


def test_one_arm_is_not_a_comparison():
    v = validate(KeywordDeclineJudge(["not from sources"]), _arm("shipped", SHIPPED_DECLINE))
    assert v.verdict is Verdict.COULD_NOT_JUDGE
    assert "two arms" in v.note


def test_no_cases_is_never_ran_not_could_not_judge():
    """Nothing was asked, so nothing was unanswerable."""
    v = validate(AlwaysPassJudge(), [])
    assert v.verdict is Verdict.NEVER_RAN
    assert v.cases == 0


def test_an_unprobed_judge_reports_never_ran():
    assert AlwaysPassJudge().validation().verdict is Verdict.NEVER_RAN
    assert not AlwaysPassJudge().validation().usable()


# ── the statistics, which have to be right or none of the above means anything ──

def test_fisher_matches_the_tea_tasting_table():
    """Fisher's own example: [[3,1],[1,3]] is 34/70 two-sided."""
    assert fisher_exact_2x2(3, 1, 1, 3) == pytest.approx(float(Fraction(34, 70)))


def test_fisher_is_symmetric_and_bounded():
    assert fisher_exact_2x2(10, 10, 0, 20) == pytest.approx(fisher_exact_2x2(0, 20, 10, 10))
    assert 0.0 <= fisher_exact_2x2(10, 10, 0, 20) <= 1.0
    assert fisher_exact_2x2(5, 5, 5, 5) == pytest.approx(1.0)


def test_a_degenerate_table_is_not_evidence():
    """No errors anywhere cannot demonstrate that errors are asymmetric."""
    assert fisher_exact_2x2(0, 20, 0, 20) == 1.0


def test_power_improves_with_cases_and_is_reported():
    """What a PASS is worth. Five per arm can only catch an enormous gap; fifty
    catches a modest one. The probe reports this so a hollow pass says so."""
    small = min_detectable_asymmetry(5, 5)
    large = min_detectable_asymmetry(50, 50)
    assert small is not None and large is not None
    assert large < small
    assert small >= 0.5      # n=5 per arm is nearly useless and admits it

    v = validate(KeywordDeclineJudge(["not from sources", "don't have reliable information"]),
                 both_arms())
    assert "smallest gap this probe could have caught" in v.bias.note


def test_youden_is_zero_for_a_judge_that_never_varies():
    assert youden_j([(Verdict.PASSED, Verdict.PASSED), (Verdict.FAILED, Verdict.PASSED)]) == 0.0
    assert youden_j([(Verdict.PASSED, Verdict.PASSED), (Verdict.FAILED, Verdict.FAILED)]) == 1.0
    assert youden_j([(Verdict.PASSED, Verdict.PASSED)]) is None    # one class only
