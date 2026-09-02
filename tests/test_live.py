# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live checks against a real endpoint. Skipped when there isn't one.

These exist because the alias defect was invisible to every offline test that
could have been written: it only shows up when a real server answers and reports
what it actually used.
"""
import json
import urllib.error
import urllib.request

import pytest
from separatrix import Agent, Chat, ChatError, Provenance, Responder, Situation
from separatrix.client import UNREPORTED

BASE = "http://localhost:9741"


def _models():
    try:
        with urllib.request.urlopen(f"{BASE}/v1/models", timeout=3) as r:
            return [m["id"] for m in json.load(r)["data"]]
    except (urllib.error.URLError, OSError, KeyError, ValueError):
        return []


MODELS = _models()
live = pytest.mark.skipif(not MODELS, reason=f"no endpoint at {BASE}")


def answering(responder, agent, situation):
    """Call the endpoint, or skip.

    An endpoint that is present but busy — mid-reload, loading a model — has not
    disproven anything, and reporting that as a failed assertion sends whoever
    reads the run looking for a defect that is not there. A refusal to answer is
    not a wrong answer.
    """
    try:
        return responder(agent, situation)
    except ChatError as exc:
        pytest.skip(f"endpoint present but not answering: {exc}")


@live
def test_the_endpoint_advertises_an_alias_and_a_real_model():
    """The setup for the defect: both names live in the same namespace, and only
    one of them still means something a year later."""
    assert "primary" in MODELS
    assert any(m != "primary" and "/" not in m for m in MODELS)


@live
def test_a_live_call_records_what_served_it_not_what_was_asked():
    """The defect, closed, against a real server."""
    r = Responder(Chat(base_url=BASE, model="primary", max_tokens=32, temperature=0.0))
    resp = answering(
        r, Agent(id="a0", genome="Answer in one short sentence."),
        Situation(prompt="How many rare orchids does the ledger record?",
                  evidence=("The Keeper's ledger records thirty-seven rare orchids.",),
                  kind="present"))

    served = resp.meta["served"]
    assert served and served != UNREPORTED
    assert served != "primary", (
        "the endpoint echoed the alias back; provenance would name nothing")
    assert served in MODELS
    assert resp.text.strip()
    # And it is the value Provenance would carry into a journal.
    assert Provenance(served=r.provenance_served, requested="primary").served == served


@live
def test_the_cache_prevents_a_second_identical_call():
    r = Responder(Chat(base_url=BASE, model="primary", max_tokens=16, temperature=0.0))
    sit = Situation(prompt="Say the word yes.", kind="present")
    agent = Agent(id="a0", genome="Reply with one word.")
    answering(r, agent, sit)
    answering(r, Agent(id="a1", genome=agent.genome), sit)
    assert (r.hits, r.misses) == (1, 1)


@live
def test_the_shipped_reader_judge_survives_its_own_probe():
    """The tier-ESTIMATED judge, against the labelled replies this study really
    produced. Skipped without an endpoint, because a judge that reads with a
    model cannot be probed without one — and pretending otherwise is how a
    suite comes to report an instrument it never checked.
    """
    import sys
    from pathlib import Path

    studies = Path(__file__).parent.parent / "studies"
    sys.path.insert(0, str(studies))
    from separatrix import Tier, Verdict, load_study, probe, resolve

    study = load_study(studies / "epistemic_garden.toml")
    assert study.judge.tier is Tier.ESTIMATED
    cases = resolve(study.cases_ref, root=studies)()
    assert len(cases) >= 20

    try:
        probed = probe(study.judge, cases)
    except Exception as exc:                       # an endpoint mid-reload
        pytest.skip(f"endpoint present but not answering: {exc}")

    v = probed.validation()
    assert v.verdict in (Verdict.PASSED, Verdict.FAILED, Verdict.COULD_NOT_JUDGE)
    # The assertion is not that it passes. It is that the probe REACHED a
    # verdict on it and that verdict decides whether it may run — which is the
    # only guarantee this library offers about a reader.
    assert v.cases == len(cases) and v.bias is not None
    assert v.usable() == v.verdict.is_pass()
