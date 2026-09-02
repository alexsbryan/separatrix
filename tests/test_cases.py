# SPDX-License-Identifier: AGPL-3.0-or-later
"""Harvesting replies to label, and reading them back as probe cases.

The bias probe is only as good as what it is fed, and this project has a
worked example of what invented cases are worth: a judge that scored 40/40 on
hand-written ones was wrong about 71% of one arm's real replies.
"""
import json

import pytest
from fake_chat import FakeChat
from separatrix import Situation, Verdict, harvest, labelled

PROBES = [Situation(prompt="who tends the south glasshouse?", kind="absent"),
          Situation(prompt="how many litres in the west cistern?", kind="absent")]
ARMS = {"grounder": "Answer only from the evidence.",
        "fabricator": "Always give a definite answer."}


def varying():
    """A model that does not say the same thing twice — which is the only kind
    worth harvesting from."""
    chat = FakeChat(lambda s, u: f"reply {len(chat.calls)} to {u[:12]}")
    return chat


# ── harvesting ──────────────────────────────────────────────────────────────

def test_harvest_writes_rows_that_carry_the_arm_and_no_label(tmp_path):
    chat = varying()
    out = tmp_path / "cases.jsonl"
    result = harvest(chat, arms=ARMS, probes=PROBES, draws=3, path=out)

    assert result["asked"] == 2 * 2 * 3 == len(chat.calls)
    rows = [json.loads(ln) for ln in out.read_text().splitlines()]
    assert len(rows) == result["distinct"] == 12
    assert {r["arm"] for r in rows} == set(ARMS)
    assert all(r["expected"] is None for r in rows), (
        "a harvested row is not a labelled one, and must not look like it")
    assert all(r["genome"] in ARMS.values() for r in rows)


def test_a_reply_the_model_repeats_is_kept_once_with_its_count(tmp_path):
    """A model that says one sentence nine times would otherwise weight that
    sentence nine times, and the probe would be measuring its favourite
    phrasing rather than the judge's fairness."""
    out = tmp_path / "cases.jsonl"
    result = harvest(FakeChat("I don't know."), arms=ARMS, probes=PROBES,
                     draws=5, path=out)
    assert result["asked"] == 20 and result["distinct"] == 4      # arms x probes
    rows = [json.loads(ln) for ln in out.read_text().splitlines()]
    assert all(r["draws"] == 5 for r in rows), "the collapse has to stay visible"


def test_harvest_will_not_overwrite_a_file_somebody_may_have_labelled(tmp_path):
    out = tmp_path / "cases.jsonl"
    harvest(varying(), arms=ARMS, probes=PROBES, draws=1, path=out)
    with pytest.raises(FileExistsError, match="by hand"):
        harvest(varying(), arms=ARMS, probes=PROBES, draws=1, path=out)


# ── reading them back ───────────────────────────────────────────────────────

def _write(tmp_path, rows):
    out = tmp_path / "cases.jsonl"
    out.write_text("\n".join(json.dumps(r) for r in rows))
    return out


ROW = {"arm": "grounder", "prompt": "who tends it?", "evidence": ["a fact"],
       "kind": "absent", "text": "I don't know.", "expected": "passed"}


def test_labelled_rows_become_cases_carrying_their_arm(tmp_path):
    out = _write(tmp_path, [ROW, {**ROW, "arm": "fabricator", "text": "Ada does.",
                                  "expected": "failed"}])
    cases = labelled(out)
    assert [c.expected for c in cases] == [Verdict.PASSED, Verdict.FAILED]
    assert [c.arm for c in cases] == ["grounder", "fabricator"]
    assert cases[0].trial.facts()["kind"] == "absent"
    assert cases[0].trial.facts()["evidence"] == ["a fact"]


def test_an_unlabelled_row_is_work_not_yet_done(tmp_path):
    """Not skipped quietly. A probe run on the rows that were easy to label is a
    probe on whichever half was easy."""
    out = _write(tmp_path, [ROW, {**ROW, "expected": None}, {**ROW, "expected": "?"}])
    with pytest.raises(ValueError, match="2 of 3 rows have no `expected`"):
        labelled(out)


def test_a_missing_file_says_how_to_make_one(tmp_path):
    with pytest.raises(FileNotFoundError, match="sep harvest"):
        labelled(tmp_path / "nothing.jsonl")


def test_a_reply_cut_off_at_the_token_limit_is_not_offered_for_labelling(tmp_path):
    """Nobody can label it, and the judges refuse it structurally. Dropped —
    and counted, because a harvest that is mostly truncation is a max_tokens
    problem and the count is how that gets noticed."""
    from separatrix import Completion

    class Cut:
        model, temperature, max_tokens = "primary", 0.8, 16
        served = "fake-model-7B"

        def __init__(self):
            self.calls = []

        def complete(self, system, user, **kw):
            self.calls.append((system, user))
            n = len(self.calls)
            return Completion(text=f"reply {n}", served=self.served,
                              finish="length" if n % 2 else "stop")

    out = tmp_path / "cases.jsonl"
    result = harvest(Cut(), arms=ARMS, probes=PROBES, draws=4, path=out)
    assert result["asked"] == 16
    assert result["truncated"] == 8 and result["distinct"] == 8
    rows = [json.loads(ln) for ln in out.read_text().splitlines()]
    assert all(r["finish"] == "stop" for r in rows)
