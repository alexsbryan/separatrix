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
from separatrix import Agent, Chat, Provenance, Responder, Situation
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
    resp = r(Agent(id="a0", genome="Answer in one short sentence."),
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
    r(agent, sit)
    r(Agent(id="a1", genome=agent.genome), sit)
    assert (r.hits, r.misses) == (1, 1)
