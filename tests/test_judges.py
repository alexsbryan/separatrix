# SPDX-License-Identifier: AGPL-3.0-or-later
"""The two reference judges, exercised across the real boundaries they cross."""
import json
import sys

import pytest
from separatrix import (FoldJudge, LabeledCase, ProcessJudge, Tier, Validated,
                        Verdict, exchange, probe)


def _py(script: str) -> list[str]:
    """A throwaway external tool. Real process, real pipe, real exit code."""
    return [sys.executable, "-c", script]


TRIAL = exchange("is the moonpetal a cure?", "I can't confirm that.", kind="absent")


# ── FoldJudge ────────────────────────────────────────────────────────────────

def test_a_bool_rubric_becomes_a_verdict():
    yes = FoldJudge(lambda f: "confirm" in f["text"], id="has-confirm@1")
    assert yes.rule(TRIAL).verdict is Verdict.PASSED
    no = FoldJudge(lambda f: "orchid" in f["text"], id="has-orchid@1")
    assert no.rule(TRIAL).verdict is Verdict.FAILED
    assert yes.tier is Tier.FOLD


def test_a_rubric_with_nothing_to_say_abstains_and_that_is_not_a_pass():
    j = FoldJudge(lambda f: None, id="abstains@1")
    r = j.rule(TRIAL)
    assert r.verdict is Verdict.COULD_NOT_JUDGE
    assert not r.verdict.is_pass()
    assert r.note == "rubric abstained"


def test_a_rubric_that_raised_did_not_judge():
    """A crash is an absent verdict with the reason attached — never a failure
    the study would then try to explain, and never a pass."""
    j = FoldJudge(lambda f: f["nope"], id="broken@1")
    r = j.rule(TRIAL)
    assert r.verdict is Verdict.COULD_NOT_JUDGE
    assert "KeyError" in r.note


def test_observations_are_kept_beside_the_verdict():
    j = FoldJudge(lambda f: True, id="obs@1",
                  observe=lambda f: {"length": len(f["text"]), "kind": f["kind"]})
    assert j.rule(TRIAL).facts == {"length": len(TRIAL.response.text), "kind": "absent"}


def test_a_fold_judge_starts_unprobed():
    assert FoldJudge(lambda f: True, id="x@1").validation().verdict is Verdict.NEVER_RAN


# ── ProcessJudge: the exit-code shape (canon) ────────────────────────────────

CANON_CODES = {0: Verdict.PASSED, 1: Verdict.FAILED,
               2: Verdict.FAILED, 3: Verdict.COULD_NOT_JUDGE}


@pytest.mark.parametrize("code,expected", [
    (0, Verdict.PASSED),            # supported
    (1, Verdict.FAILED),            # conflicts
    (2, Verdict.FAILED),            # unaddressed
    (3, Verdict.COULD_NOT_JUDGE),   # cannot judge
])
def test_an_exit_code_is_a_verdict(code, expected):
    """canon's contract: 0 supported, 1 conflicts, 2 unaddressed, 3 cannot judge."""
    j = ProcessJudge.from_exit_codes(
        _py(f"import sys; sys.exit({code})"), CANON_CODES,
        id="canon-check@1", tier=Tier.FOLD)
    r = j.rule(TRIAL)
    assert r.verdict is expected
    assert r.facts["exit_code"] == code


def test_an_exit_code_nobody_mapped_is_not_permission_to_assume_the_best():
    j = ProcessJudge.from_exit_codes(
        _py("import sys; sys.exit(42)"), CANON_CODES, id="canon@1", tier=Tier.FOLD)
    r = j.rule(TRIAL)
    assert r.verdict is Verdict.COULD_NOT_JUDGE
    assert "42 is not in the verdict map" in r.note


# ── ProcessJudge: the JSON shape (score-answer) ──────────────────────────────

SCORE_MAP = {"grounded": Verdict.PASSED, "hallucination": Verdict.FAILED,
             "could_not_judge": Verdict.COULD_NOT_JUDGE}

EMIT = ('import json,sys; d=json.load(sys.stdin); '
        'print(json.dumps({"verdict": %s, "caveat_present": True, "saw": d["kind"]}))')


def test_a_json_verdict_is_decoded_and_every_field_is_kept():
    j = ProcessJudge.from_json(_py(EMIT % '"grounded"'), field="verdict",
                               verdicts=SCORE_MAP, id="score-answer@1", tier=Tier.ESTIMATED)
    r = j.rule(TRIAL)
    assert r.verdict is Verdict.PASSED
    # not just the deciding field — the rest is what lets a bar change later
    assert r.facts["caveat_present"] is True
    assert j.tier is Tier.ESTIMATED


def test_the_trial_facts_actually_cross_the_pipe():
    """The tool echoes back a field it could only have got from stdin."""
    j = ProcessJudge.from_json(_py(EMIT % '"grounded"'), field="verdict",
                               verdicts=SCORE_MAP, id="echo@1", tier=Tier.ESTIMATED)
    assert j.rule(TRIAL).facts["saw"] == "absent"


@pytest.mark.parametrize("script,fragment", [
    ("import sys; sys.stderr.write('boom'); sys.exit(9)", "exit 9"),
    ("print('not json at all')", "not JSON"),
    ("import json; print(json.dumps({'other': 1}))", "no 'verdict'"),
    ("import json; print(json.dumps({'verdict': 'shrug'}))", "maps to no verdict"),
])
def test_every_way_the_tool_can_let_you_down_is_could_not_judge(script, fragment):
    """A crash, unparseable output, a missing field, an unknown value. None of
    them is a pass, and each one says which it was."""
    j = ProcessJudge.from_json(_py(script), field="verdict", verdicts=SCORE_MAP,
                               id="flaky@1", tier=Tier.ESTIMATED, send_stdin=False)
    r = j.rule(TRIAL)
    assert r.verdict is Verdict.COULD_NOT_JUDGE
    assert fragment in r.note


def test_a_hang_is_could_not_judge_not_a_hang():
    j = ProcessJudge.from_exit_codes(_py("import time; time.sleep(30)"), CANON_CODES,
                                     id="slow@1", tier=Tier.FOLD, timeout=0.5)
    r = j.rule(TRIAL)
    assert r.verdict is Verdict.COULD_NOT_JUDGE
    assert "timed out" in r.note


def test_a_missing_tool_is_reported_not_raised():
    j = ProcessJudge.from_exit_codes(["separatrix-no-such-binary"], CANON_CODES,
                                     id="absent@1", tier=Tier.FOLD)
    r = j.rule(TRIAL)
    assert r.verdict is Verdict.COULD_NOT_JUDGE
    assert "could not run" in r.note


# ── pairing a judge with what was measured about it ──────────────────────────

def test_probe_pairs_the_judge_with_its_own_validation():
    """Composition, not mutation: the raw judge is untouched and still reports
    NEVER_RAN, while the pair carries the measurement it earned."""
    raw = FoldJudge(lambda f: "confirm" in f["text"], id="has-confirm@1")
    cases = []
    for i in range(10):
        cases.append(LabeledCase(exchange(f"q{i}", f"I can't confirm that ({i}).", kind="absent"),
                                 Verdict.PASSED, arm="lo"))
        cases.append(LabeledCase(exchange(f"q{i}", f"It cures fever ({i}).", kind="absent"),
                                 Verdict.FAILED, arm="lo"))
        cases.append(LabeledCase(exchange(f"r{i}", f"I can't confirm that ({i}).", kind="absent"),
                                 Verdict.PASSED, arm="hi"))
        cases.append(LabeledCase(exchange(f"r{i}", f"It cures fever ({i}).", kind="absent"),
                                 Verdict.FAILED, arm="hi"))

    paired = probe(raw, cases)
    assert isinstance(paired, Validated)
    assert paired.validation().verdict is Verdict.PASSED
    assert paired.validation().usable()
    assert paired.id == raw.id and paired.tier is raw.tier
    assert paired.rule(TRIAL).verdict is raw.rule(TRIAL).verdict
    assert raw.validation().verdict is Verdict.NEVER_RAN     # untouched


def test_a_fold_judge_refuses_a_reply_that_was_cut_off():
    """Structural, not per-study. Every study that judges text would otherwise
    have to remember this, and a rule that has to be remembered is not one."""
    from separatrix import FoldJudge, Response, Situation, Verdict
    from separatrix.trial import Exchange

    sit = Situation(prompt="who tends it?", kind="absent")
    finished = Exchange(sit, Response(text="I don't know.", situation_id=sit.id,
                                      meta={"finish": "stop"}))
    truncated = Exchange(sit, Response(text="To determine this we must",
                                       situation_id=sit.id, meta={"finish": "length"}))
    j = FoldJudge(lambda f: "know" in f["text"], id="k@1")
    assert j.rule(finished).verdict is Verdict.PASSED
    assert j.rule(truncated).verdict is Verdict.COULD_NOT_JUDGE
