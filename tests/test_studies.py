# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every shipped study loads, and every shipped judge survives its own probe."""
from pathlib import Path

import pytest
from separatrix import Tier, Verdict, load_study, validate

STUDIES = sorted((Path(__file__).parent.parent / "studies").glob("*.toml"))


def _cases(study):
    cases = study.cases()
    assert cases, f"{study.name} declares no cases, so its judge cannot be probed"
    return cases


def test_there_are_studies_to_check():
    assert len(STUDIES) >= 4


@pytest.mark.parametrize("path", STUDIES, ids=lambda p: p.stem)
def test_a_shipped_study_loads_and_declares_what_probes_it(path):
    study = load_study(path)
    assert study.name and study.coordinate and study.outcome
    assert study.cases() is not None, (
        "a study that declares no cases cannot be run at all")
    assert len(_cases(study)) >= 20


@pytest.mark.parametrize("path", STUDIES, ids=lambda p: p.stem)
def test_a_shipped_fold_judge_passes_its_own_probe(path):
    """A study whose judge cannot be probed cannot be run, so shipping one is
    shipping something nobody can use.

    Only the folds are checked here, and that is not an exemption for the rest:
    an ESTIMATED judge cannot be probed without the endpoint it reads with, so
    its probe belongs in `test_live.py` where it can be skipped honestly rather
    than in a suite that must pass on a laptop with no model.
    """
    study = load_study(path)
    if study.judge.tier is not Tier.FOLD:
        pytest.skip(f"{study.judge.id} is tier={study.judge.tier.value}; probing it "
                    f"needs a model (see tests/test_live.py)")
    v = validate(study.judge, _cases(study))
    assert v.verdict is Verdict.PASSED, f"{study.name}: {v.note}"
    assert v.discrimination is not None and v.discrimination > 0.2
    assert set(v.bias.arms) and len(v.bias.arms) == 2


@pytest.mark.parametrize("path", STUDIES, ids=lambda p: p.stem)
def test_a_shipped_study_declares_a_journal_and_a_budget(path):
    study = load_study(path)
    assert study.journal_path.name.endswith(".jsonl")
    assert study.budget.runs >= 2 * study.replicates, (
        "a budget below 2x replicates cannot even measure noise")


# ── telephone's outcome, and the zero it must not drop ───────────────────────

def _hop(claim, teller, rnd, verdict, *, rounds=4, grounded=False):
    from separatrix import Ruling
    return Ruling(verdict=verdict, trial_id=f"{claim}-{teller}-{rnd}", judge="j@1",
                  facts={"claim": claim, "teller": teller, "round": rnd,
                         "claim_grounded": grounded, "rounds": rounds})


def test_a_round_the_institution_silenced_completely_is_a_round_of_zero_reach():
    """A round in which every chain was quarantined produces NO rulings. Averaging
    over the rounds that survived turns total suppression into an absence and
    reports it as reach unchanged — the mean of [2] and the mean of [2, 0] are
    not the same number, and the second is the one that happened.

    This is not hypothetical: the first reconstruction of `telephone`'s cost
    ratio in this repo dropped exactly these rounds and came out 60% high.
    `PREREGISTRATION.md` A16.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "studies"))
    from telephone import false_reach

    spread_every_round = [_hop("cure", t, r, Verdict.FAILED)
                          for r in range(4) for t in ("Ada", "Boro")]
    assert false_reach(spread_every_round) == 2.0

    # Same spreading, but the institution silenced rounds 2 and 3 entirely.
    silenced_half = [_hop("cure", t, r, Verdict.FAILED)
                     for r in range(2) for t in ("Ada", "Boro")]
    assert false_reach(silenced_half) == 1.0        # not 2.0


def test_a_teller_that_refuses_the_rumour_is_not_reach():
    """A9's rule, still enforced after A16 moved the count per-round."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "studies"))
    from telephone import false_reach

    refused = [_hop("cure", "Ada", r, Verdict.PASSED, rounds=2) for r in range(2)]
    assert false_reach(refused) == 0.0
