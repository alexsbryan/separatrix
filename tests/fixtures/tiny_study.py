# SPDX-License-Identifier: AGPL-3.0-or-later
"""A study with no model at all: scenarios, a policy, a fold."""
from separatrix import FoldJudge, LabeledCase, Replay, RowTrial, Scenario, Verdict

SCENARIOS = [Scenario(id=f"s{h}", facts={"hour": h}) for h in range(18, 26)]

judge = FoldJudge(lambda f: f["hour"] >= f["quiet_from"], id="quiet-hours@1",
                  observe=lambda f: {"hour": f["hour"]})


def cases():
    """Labelled cases from both ends of the coordinate.

    Note the trial shape: `RowTrial`, not `Exchange`. A judge that reads hours
    cannot be probed with cases that carry utterances, and the first version of
    this fixture made exactly that mistake — the probe scored zero
    discrimination and refused the study, which is the gate working.
    """
    out = []
    for i in range(5):
        for arm, policy in (("early", 19), ("late", 24)):
            out += [
                LabeledCase(RowTrial({"hour": policy + 1 + i}, {"quiet_from": policy}, i),
                            Verdict.PASSED, arm=arm),
                LabeledCase(RowTrial({"hour": policy - 1 - i}, {"quiet_from": policy}, i),
                            Verdict.FAILED, arm=arm),
            ]
    return out


def quiet_rate(rulings):
    return sum(r.verdict.is_pass() for r in rulings) / len(rulings) if rulings else 0.0


def arena(*, study, journal):
    return Replay(SCENARIOS, journal=journal)
