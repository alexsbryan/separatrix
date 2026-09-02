# SPDX-License-Identifier: AGPL-3.0-or-later
"""The founding failure, reproduced on this project's own flagship study.

`epistemic_garden.keyword_judge` produced the numbers this repository published
for a month, and those numbers were a measurement of decline vocabulary. It is
kept, and this file is why: the whole claim of the library is that a reader
whose errors track the swept coordinate manufactures findings, and asserting
that in prose is worth less than asserting it in a test that would fail if the
keyword judge were quietly repaired.

Offline. It reads the committed, hand-labelled replies — no model, no endpoint.
The reader judge's own probe needs one and lives in `test_live.py`.
"""
import sys
from pathlib import Path

import pytest

STUDIES = Path(__file__).parent.parent / "studies"
sys.path.insert(0, str(STUDIES))

from separatrix import Verdict, validate                       # noqa: E402


@pytest.fixture(scope="module")
def cases():
    import epistemic_garden
    return epistemic_garden.cases()


def test_the_labelled_replies_cover_both_arms_and_both_verdicts(cases):
    """A probe needs both classes in both arms or it measures something
    narrower than it claims — and a case set with only declines in it is what
    the first version of this study had."""
    arms = {c.arm for c in cases}
    assert arms == {"fabricator", "grounder"}
    for arm in arms:
        got = {c.expected for c in cases if c.arm == arm}
        assert got, arm
    assert {c.expected for c in cases} == {Verdict.PASSED, Verdict.FAILED}


def test_the_keyword_judge_is_refused_on_replies_the_study_really_produced(cases):
    """The retraction, as a gate.

    It knows `"I don't know"` — the phrase the high end of the coordinate
    selects for — and not `"impossible to determine"` or `"there is no mention
    of"`, which is what the low end says. Its blind spot IS the coordinate.
    """
    import epistemic_garden

    v = validate(epistemic_garden.keyword_judge, cases)
    assert v.verdict is Verdict.FAILED, (
        f"the keyword judge passed its probe ({v.note}). If it was repaired, "
        f"this test should be deleted along with the retraction it guards — but "
        f"not quietly, and not by widening the word list until the probe stops "
        f"complaining, which is teaching to the test.")

    errors = {arm: row["error_rate"] for arm, row in v.bias.arms.items()}
    assert errors["fabricator"] > errors["grounder"], (
        "the whole point is WHICH arm the errors fall on")
    assert v.bias.p_value is not None and v.bias.p_value < 0.05


def test_the_synthetic_cases_it_used_to_pass_on_were_the_problem():
    """Not the tier, and not the rule. The cases.

    Hand-written ones had the confident arm decline with "That is not stated in
    the sources" — a phrase the word list happens to know — so every judge shown
    them scored full marks. This is that set, and the pass it still produces.
    """
    from separatrix import LabeledCase, Verdict, exchange
    import epistemic_garden

    invented = []
    for i in range(10):
        invented += [
            LabeledCase(exchange(f"q{i}", f"I don't know ({i}).", kind="absent"),
                        Verdict.PASSED, arm="grounder"),
            LabeledCase(exchange(f"q{i}", f"It is thirty-seven ({i}).", kind="absent"),
                        Verdict.FAILED, arm="grounder"),
            LabeledCase(exchange(f"r{i}", f"That is not stated in the sources ({i}).",
                                 kind="absent"), Verdict.PASSED, arm="fabricator"),
            LabeledCase(exchange(f"r{i}", f"It is forty-one ({i}).", kind="absent"),
                        Verdict.FAILED, arm="fabricator"),
        ]

    v = validate(epistemic_garden.keyword_judge, invented)
    assert v.verdict is Verdict.PASSED and v.discrimination == 1.0, (
        "40/40 on invented cases, and refused on the real ones. That gap is the "
        "reason `sep harvest` exists.")


# ── the same lesson, in its other form ──────────────────────────────────────

def test_the_move_reader_is_blind_rather_than_biased():
    """Four verdicts earning their keep.

    `trust_game`'s word list is not wrong in one direction — it cannot tell the
    classes apart at all. Every reply this model gives WEIGHS defection before
    choosing ("defecting offers a higher payoff (8) ... Therefore, Cooperate"),
    and a stem list sees the word. Discrimination 0.00.

    That is a different failure from the garden's and it gets a different
    verdict: bias is not measurable through a blindfold, so the probe returns
    COULD_NOT_JUDGE rather than FAILED. Both refuse the sweep; only one of them
    is a claim about which arm the errors fall on.
    """
    import trust_game

    v = validate(trust_game.keyword_judge, trust_game.cases())
    assert v.verdict is Verdict.COULD_NOT_JUDGE
    assert v.discrimination == 0.0
    assert "cannot separate the classes" in v.note
    assert v.bias.p_value is None, (
        "no p-value, because there is nothing to test through a blind judge")


def test_mention_is_not_use_and_no_word_list_fixes_that():
    """Why the repair is a reader and not a longer stem list.

    The same word carries the opposite meaning in a reply that defects and in
    one that decides against defecting. There is no phrase to add.
    """
    import trust_game

    decided_to_cooperate = ("Defecting offers a higher individual payoff (8), but "
                            "it risks mutual defection. Therefore, **Cooperate**.")
    assert trust_game.cooperated(decided_to_cooperate) is False, (
        "the word list reads this as a defection — that is the defect")
