# SPDX-License-Identifier: AGPL-3.0-or-later
"""A study is a TOML file plus a judge function."""
import shutil
from pathlib import Path

import pytest
from separatrix import Verdict, load_study, resolve
from separatrix.__main__ import main as cli

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def study_dir(tmp_path):
    for name in ("tiny_study.py", "tiny_study.toml"):
        shutil.copy(FIXTURES / name, tmp_path / name)
    return tmp_path


def test_the_data_half_is_data(study_dir):
    s = load_study(study_dir / "tiny_study.toml")
    assert s.name == "tiny"
    assert (s.coordinate.name, s.coordinate.lo, s.coordinate.hi) == ("quiet_from", 18.0, 26.0)
    assert s.outcome.threshold == 0.5
    assert s.budget.runs == 20 and s.replicates == 2
    assert s.judge.id == "quiet-hours@1"


def test_a_missing_key_names_itself(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('[study]\nname = "x"\n')
    with pytest.raises(ValueError, match=r"needs a 'judge'"):
        load_study(bad)


def test_a_dotted_reference_that_does_not_resolve_says_which_half(study_dir):
    with pytest.raises(ValueError, match="has no 'nope'"):
        resolve("tiny_study:nope", root=study_dir)
    with pytest.raises(ValueError, match="cannot import"):
        resolve("no_such_module:x", root=study_dir)
    with pytest.raises(ValueError, match="must be 'module:attribute'"):
        resolve("bare_name")


def test_a_study_refuses_to_spend_before_its_judge_is_probed(study_dir, capsys):
    """The charter's gate, at the front door. No cases, no run."""
    code = cli(["run", str(study_dir / "tiny_study.toml")])
    assert code == 3
    assert "refusing to spend" in capsys.readouterr().err


def test_a_probed_study_sweeps_and_journals_with_no_model(study_dir, capsys):
    code = cli(["run", str(study_dir / "tiny_study.toml"), "--cases", "tiny_study:cases"])
    out = capsys.readouterr().out
    assert "PASSED" in out and "quiet_from flips in" in out
    assert "(no model)" in out
    assert code == 0

    journal = study_dir / "tiny.jsonl"
    assert journal.exists()
    assert cli(["bracket", str(journal)]) == 0
    assert "matches what was recorded" in capsys.readouterr().out


def test_the_journal_header_carries_the_probed_validation(study_dir):
    import json
    cli(["run", str(study_dir / "tiny_study.toml"), "--cases", "tiny_study:cases"])
    header = json.loads((study_dir / "tiny.jsonl").read_text().splitlines()[0])
    v = header["judge"]["validation"]
    assert v["verdict"] == "passed" and v["tier"] == "fold"
    assert v["bias"]["p_value"] is not None
    assert v["cases"] == 20 and set(v["bias"]["arms"]) == {"early", "late"}
    # A weak pass says so: 10 per arm can only catch a very large asymmetry.
    assert "smallest gap this probe could have caught" in v["note"]
