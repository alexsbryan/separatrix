# SPDX-License-Identifier: AGPL-3.0-or-later
"""The model layer: what it records, and what it refuses to pay for twice."""
import json
from unittest import mock

import pytest
from fake_chat import FakeChat
from separatrix import (Agent, Chat, ChatError, Journal, Provenance, Responder,
                        Situation, strip_think)
from separatrix.client import UNREPORTED

SIT = Situation(prompt="how many orchids?", evidence=("the ledger records 37",))


# ── the served id, which is the whole point ─────────────────────────────────

def test_served_comes_from_the_response_not_the_request():
    """Ask for an alias, record what answered. This is the defect that made a
    body of published tables name nothing."""
    chat = FakeChat("37.", served="Qwen3.6-35B-A3B-MTP-UD-Q6_K", model="primary")
    r = Responder(chat)
    resp = r(Agent(id="a0", genome="Answer from the evidence."), SIT)
    assert resp.meta["served"] == "Qwen3.6-35B-A3B-MTP-UD-Q6_K"
    assert r.provenance_served == "Qwen3.6-35B-A3B-MTP-UD-Q6_K"
    assert chat.model == "primary"          # the alias is what we ASKED


def test_a_server_that_reports_no_model_says_so_rather_than_borrowing_the_alias():
    r = Responder(FakeChat("37.", served=""))
    r(Agent(id="a0", genome="g"), SIT)
    assert r.provenance_served == UNREPORTED
    assert Provenance(served=r.provenance_served).served == UNREPORTED


def test_an_endpoint_that_changes_model_mid_run_is_recorded_loudly(tmp_path):
    """A comparison spanning two models is not the comparison anyone thinks they
    ran, so it must be visible rather than averaged in."""
    chat = FakeChat("x", served=lambda n: "model-A" if n < 3 else "model-B")
    path = tmp_path / "j.jsonl"
    with Journal(path, Provenance(served="model-A")) as j:
        r = Responder(chat, journal=j)
        for i in range(4):
            r(Agent(id=f"a{i}", genome=f"genome {i}"), SIT)

    changes = [json.loads(ln) for ln in path.read_text().splitlines()
               if '"model_changed"' in ln]
    assert len(changes) == 1 and changes[0]["now"] == "model-B"
    assert r.provenance_served == "model-A + model-B"


# ── the cache, which is why a sweep is affordable ───────────────────────────

def test_the_same_genome_asked_the_same_thing_is_one_call():
    """Two agents holding an identical genome are the same call. At these
    sample costs, paying twice is money set on fire."""
    chat = FakeChat("37.")
    r = Responder(chat)
    r(Agent(id="a0", genome="same"), SIT)
    r(Agent(id="a1", genome="same"), SIT)
    assert len(chat.calls) == 1
    assert (r.hits, r.misses) == (1, 1)


def test_a_different_genome_is_a_different_call():
    chat = FakeChat("37.")
    r = Responder(chat)
    r(Agent(id="a0", genome="one"), SIT)
    r(Agent(id="a0", genome="two"), SIT)
    assert len(chat.calls) == 2


def test_a_cache_folded_off_a_journal_resumes_for_free(tmp_path):
    from separatrix import Run

    path = tmp_path / "j.jsonl"
    chat = FakeChat("37.")
    with Journal(path, Provenance(served="m")) as j:
        Responder(chat, journal=j)(Agent(id="a0", genome="g"), SIT)
    assert len(chat.calls) == 1

    warm = Responder(FakeChat("should never be called"), cache=Run.load(path).cache())
    resp = warm(Agent(id="a9", genome="g"), SIT)
    assert resp.text == "37." and resp.meta["cached"] is True


def test_temperature_is_part_of_the_key():
    a, b = FakeChat("x", temperature=0.1), FakeChat("x", temperature=0.9)
    agent, key = Agent(id="a", genome="g"), None
    key = Responder(a).key(agent, SIT)
    assert key != Responder(b).key(agent, SIT)


# ── the client itself ───────────────────────────────────────────────────────

def _http(body, status=200):
    resp = mock.MagicMock()
    resp.read.return_value = json.dumps(body).encode()
    resp.__enter__.return_value = resp
    return resp


def test_the_client_reads_the_served_model_off_the_body():
    body = {"model": "Qwen3.6-35B-A3B", "choices": [{"message": {"content": " 37. "}}]}
    with mock.patch("urllib.request.urlopen", return_value=_http(body)):
        c = Chat().complete("sys", "user")
    assert c.served == "Qwen3.6-35B-A3B" and c.text == "37."


def test_a_response_with_no_completion_is_an_error_not_an_empty_answer():
    """A run that could not get an answer must not look like one that got a bad
    answer, so this raises rather than returning ''."""
    with mock.patch("urllib.request.urlopen", return_value=_http({"model": "m"})):
        with pytest.raises(ChatError, match="no completion"):
            Chat().complete("sys", "user")


def test_an_unreachable_endpoint_names_itself():
    import urllib.error
    with mock.patch("urllib.request.urlopen",
                    side_effect=urllib.error.URLError("refused")):
        with pytest.raises(ChatError, match="cannot reach"):
            Chat(base_url="http://localhost:9").complete("s", "u")


@pytest.mark.parametrize("raw,want", [
    ("<think>hmm</think>The answer.", "The answer."),
    ("<think>a</think>X<think>b</think>Y", "XY"),
    ("<think>never closed", ""),
    ("plain", "plain"),
])
def test_leaked_reasoning_is_stripped(raw, want):
    """A genome contaminated with a reasoning block is not the strategy that was
    selected."""
    assert strip_think(raw) == want
