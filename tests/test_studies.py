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
