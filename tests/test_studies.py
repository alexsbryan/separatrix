# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every shipped study loads, and every shipped judge survives its own probe."""
from pathlib import Path

import pytest
from separatrix import Verdict, load_study, resolve, validate

STUDIES = sorted((Path(__file__).parent.parent / "studies").glob("*.toml"))


def test_there_are_studies_to_check():
    assert len(STUDIES) >= 4


@pytest.mark.parametrize("path", STUDIES, ids=lambda p: p.stem)
def test_a_shipped_study_loads_and_its_judge_passes_its_own_probe(path):
    """A study whose judge cannot be probed cannot be run, so shipping one is
    shipping something nobody can use."""
    study = load_study(path)
    assert study.name and study.coordinate and study.outcome

    cases = resolve(f"{path.stem}:cases", root=path.parent)()
    v = validate(study.judge, cases)
    assert v.verdict is Verdict.PASSED, f"{study.name}: {v.note}"
    assert v.discrimination is not None and v.discrimination > 0.2
    assert set(v.bias.arms) and len(v.bias.arms) == 2


@pytest.mark.parametrize("path", STUDIES, ids=lambda p: p.stem)
def test_a_shipped_study_declares_a_journal_and_a_budget(path):
    study = load_study(path)
    assert study.journal_path.name.endswith(".jsonl")
    assert study.budget.runs >= 2 * study.replicates, (
        "a budget below 2x replicates cannot even measure noise")
