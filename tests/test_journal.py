# SPDX-License-Identifier: AGPL-3.0-or-later
"""The log, and the fold that has to be able to stand in for the run."""
import json

import pytest
from separatrix import Journal, Provenance, Ruling, Run, Verdict, exchange, replay
from separatrix.journal import NO_MODEL, response_key
from separatrix.__main__ import main


def _prov(**kw):
    return Provenance(served="Qwen3.6-35B-A3B-MTP-UD-Q6_K", requested="primary",
                      endpoint="http://localhost:9741", **kw)


# ── the guard that exists because of a real six-week-old mistake ─────────────

def test_a_journal_cannot_record_an_alias_as_if_it_were_a_model():
    """The sandbox recorded "model": "primary" everywhere. The alias was later
    repointed, so which model produced its published tables is now unrecoverable
    — by anyone, including its author. This is that failure made unconstructable."""
    with pytest.raises(ValueError, match="SERVER reported"):
        Provenance(served="")
    with pytest.raises(ValueError, match="SERVER reported"):
        Provenance(served="   ")


def test_a_study_with_no_model_says_so_explicitly():
    """A canon-replay study has no model at all. That is a statement it makes,
    not a default it falls into."""
    p = Provenance.modelless(endpoint="")
    assert p.served == NO_MODEL
    assert not p.alias_was_repointed_risk


def test_the_alias_is_kept_beside_what_served_it():
    p = _prov()
    assert p.requested == "primary" and p.served.startswith("Qwen3.6")
    assert p.alias_was_repointed_risk        # they differ, which is the normal case


# ── writing and folding ─────────────────────────────────────────────────────

def _write(path, verdicts, *, responses=()):
    with Journal(path, _prov(), config={"agents": 6}, judge={"id": "fold@1"}) as j:
        for i, v in enumerate(verdicts):
            j.ruling(Ruling(verdict=v, trial_id=f"t{i}", judge="fold@1",
                            note="" if v.is_judged() else "rubric abstained"))
        for key, text in responses:
            j.response(key, text, served="Qwen3.6-35B-A3B-MTP-UD-Q6_K")
    return path


def test_a_run_folds_back_to_its_counts_and_its_verdict(tmp_path):
    p = _write(tmp_path / "r.jsonl", [Verdict.PASSED, Verdict.PASSED, Verdict.FAILED])
    run = Run.load(p)
    assert run.counts() == {"passed": 2, "failed": 1}
    assert run.verdict() is Verdict.FAILED          # never rescued by its neighbours
    assert run.served == "Qwen3.6-35B-A3B-MTP-UD-Q6_K"


def test_an_unjudged_ruling_never_becomes_a_pass_in_the_fold(tmp_path):
    p = _write(tmp_path / "r.jsonl", [Verdict.PASSED, Verdict.COULD_NOT_JUDGE])
    run = Run.load(p)
    assert run.verdict() is Verdict.COULD_NOT_JUDGE
    assert len(run.unjudged()) == 1
    assert run.unjudged()[0]["note"] == "rubric abstained"


def test_an_empty_run_does_not_pass(tmp_path):
    p = _write(tmp_path / "r.jsonl", [])
    assert Run.load(p).verdict() is Verdict.NEVER_RAN


# ── resume and cache: the two things append-only buys ───────────────────────

def test_reopening_appends_and_writes_one_header(tmp_path):
    p = tmp_path / "r.jsonl"
    _write(p, [Verdict.PASSED])
    _write(p, [Verdict.FAILED])
    headers = [r for r in map(json.loads, p.read_text().splitlines()) if r["t"] == "header"]
    assert len(headers) == 1
    assert len(Run.load(p).rulings) == 2


def test_the_journal_is_the_cache(tmp_path):
    """Resume is a fold, not a feature. A re-sweep reuses every sample the
    changed coordinate did not touch."""
    k1, k2 = response_key(prompt="a", genome="g1"), response_key(prompt="b", genome="g1")
    p = _write(tmp_path / "r.jsonl", [Verdict.PASSED],
               responses=[(k1, "first answer"), (k2, "second answer")])
    assert Run.load(p).cache() == {k1: "first answer", k2: "second answer"}


def test_a_response_key_changes_only_with_what_would_change_the_answer():
    assert response_key(prompt="a", genome="g") == response_key(genome="g", prompt="a")
    assert response_key(prompt="a", genome="g") != response_key(prompt="a", genome="h")


def test_a_corrupt_line_names_itself(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text('{"t":"header"}\nnot json\n')
    with pytest.raises(ValueError, match=r":2 is not valid JSON"):
        list(Run.load(p).rulings)


# ── the property the whole phase exists for ─────────────────────────────────

def test_replay_needs_no_model_and_no_endpoint(tmp_path, monkeypatch):
    """Re-deriving a published number must not require the thing that produced
    it. Sockets are disabled for the duration; the fold must not notice."""
    import socket

    p = _write(tmp_path / "r.jsonl", [Verdict.PASSED, Verdict.PASSED, Verdict.FAILED])

    def no_sockets(*a, **k):
        raise AssertionError("replay opened a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)

    out = replay(p)
    assert out["counts"] == {"passed": 2, "failed": 1}
    assert out["verdict"] == "failed"
    assert out["served"] == "Qwen3.6-35B-A3B-MTP-UD-Q6_K"


def test_sep_replay_prints_the_run_and_exits_on_its_verdict(tmp_path, capsys):
    p = _write(tmp_path / "r.jsonl", [Verdict.PASSED, Verdict.FAILED])
    code = main(["replay", str(p)])
    out = capsys.readouterr().out
    assert code == 1                       # the run failed, so the command does
    assert "Qwen3.6-35B-A3B" in out and "verdict   FAILED" in out

    ok = _write(tmp_path / "ok.jsonl", [Verdict.PASSED])
    assert main(["replay", str(ok)]) == 0


def test_sep_replay_json_is_the_same_fold(tmp_path, capsys):
    p = _write(tmp_path / "r.jsonl", [Verdict.PASSED])
    main(["replay", str(p), "--json"])
    assert json.loads(capsys.readouterr().out) == replay(p)


def test_a_journal_with_no_provenance_is_flagged_loudly(tmp_path, capsys):
    """An old-style journal that names nothing should not read as a clean run."""
    p = tmp_path / "legacy.jsonl"
    p.write_text('{"t":"ruling","verdict":"passed","trial_id":"t0","judge":"x"}\n')
    main(["replay", str(p)])
    assert "records no served model" in capsys.readouterr().err


# ── one journal, several runs ───────────────────────────────────────────────

def test_a_run_id_survives_being_reopened(tmp_path):
    """Resume is the whole point of an append-only log. A run id carrying a
    clock can never be recognised again, so a crashed run reopened five minutes
    later becomes a different run and its samples become someone else's."""
    import time

    a = Journal(tmp_path / "r.jsonl", _prov(), config={"x": 1})
    time.sleep(0.01)
    b = Journal(tmp_path / "r.jsonl", _prov(), config={"x": 1})
    assert a.run_id == b.run_id

    c = Journal(tmp_path / "r.jsonl", _prov(), config={"x": 2})
    assert c.run_id != a.run_id          # a different study IS a different run


def test_each_run_gets_its_own_header_and_folds_separately(tmp_path):
    path = tmp_path / "many.jsonl"
    with Journal(path, _prov(), config={"x": 1}) as j:
        j.ruling(Ruling(verdict=Verdict.PASSED, trial_id="t0", judge="j@1"))
    with Journal(path, _prov(), config={"x": 2}) as j:
        j.ruling(Ruling(verdict=Verdict.FAILED, trial_id="t1", judge="j@1"))
        j.ruling(Ruling(verdict=Verdict.FAILED, trial_id="t2", judge="j@1"))

    assert len(Run.runs(path)) == 2
    latest = Run.load(path)                       # defaults to the most recent
    assert latest.counts() == {"failed": 2}
    first = Run.load(path, Run.runs(path)[0])
    assert first.counts() == {"passed": 1}
    assert first.header["config"] == {"x": 1}


def test_a_restarted_sweep_does_not_re_derive_a_search_nobody_ran(tmp_path):
    """Two sweeps in one run leave two sets of samples. Folding both would
    interleave two searches into one bracket."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_sweep import COORD, StepArena, Y, _judge

    from separatrix import Budget, bracket_from_records, sweep

    path = tmp_path / "twice.jsonl"
    with Journal(path, _prov(), config={"k": 1}) as j:
        sweep(StepArena(flip=0.8), _judge(), COORD, Y,
              budget=Budget(runs=12), replicates=2, journal=j)
        live = sweep(StepArena(flip=0.2), _judge(), COORD, Y,
                     budget=Budget(runs=12), replicates=2, journal=j)

    again = bracket_from_records(Run.load(path).other, threshold=Y.threshold, name="y")
    assert (again.lo, again.hi) == (live.lo, live.hi)
    assert again.lo <= 0.2 <= again.hi        # the second search, not a blend
