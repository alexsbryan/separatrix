# SPDX-License-Identifier: AGPL-3.0-or-later
"""The only place a model is called, and the only place `served` comes from.

Plain OpenAI-compatible `/v1/chat/completions` over stdlib urllib, so this
reaches Ollama, vLLM, llama.cpp's server, LM Studio and the hosted APIs without
a dependency.

**The served id is read from the RESPONSE, never from the request.** Asking for
`primary` and recording `primary` is how a body of published results came to
name nothing: the alias was later repointed, and which model produced those
tables is now unrecoverable by anyone. The response body carries the id the
server actually used, so reading it costs nothing — and when a server declines
to report one, that fact is recorded verbatim rather than backfilled with the
alias, which would be the same mistake wearing a disguise.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = ["Completion", "Chat", "ChatError", "strip_think", "UNREPORTED"]

UNREPORTED = "(server reported no model)"


class ChatError(RuntimeError):
    """The endpoint did not produce a usable completion. Never swallowed: a run
    that could not get an answer must not look like a run that got a bad one."""


def strip_think(text: str) -> str:
    """Remove reasoning blocks a model leaked into its answer.

    Small reasoning models emit `<think>` spans that no amount of prompting
    reliably suppresses, and a strategy genome contaminated with one is not the
    strategy that was selected. A safety net, not a substitute for a clean model.
    """
    out, low = text, text.lower()
    while (start := low.find("<think>")) != -1:
        end = low.find("</think>", start)
        out = out[:start] + (out[end + 8:] if end != -1 else "")
        low = out.lower()
    return out.strip()


@dataclass(frozen=True)
class Completion:
    text: str
    served: str                                  # from the response body
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class Chat:
    """One endpoint, one requested model."""

    base_url: str = "http://localhost:9741"
    model: str = "primary"
    timeout: float = 120.0
    temperature: float = 0.8
    max_tokens: int = 512

    @property
    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/v1/chat/completions"

    def complete(self, system: str, user: str, *, temperature: float | None = None,
                 max_tokens: int | None = None, response_format: Mapping | None = None
                 ) -> Completion:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        if response_format:
            payload["response_format"] = dict(response_format)

        req = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ChatError(f"{self.endpoint} returned {exc.code}: "
                            f"{exc.read()[:400].decode('utf-8', 'replace')}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ChatError(f"cannot reach {self.endpoint}: {exc}") from None
        except json.JSONDecodeError as exc:
            raise ChatError(f"{self.endpoint} did not return JSON: {exc}") from None

        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ChatError(f"no completion in the response: "
                            f"{json.dumps(body)[:400]}") from None

        # The whole reason this function exists in one place.
        served = str(body.get("model") or "").strip() or UNREPORTED
        return Completion(text=strip_think(text or ""), served=served, raw=body)

    def probe_served(self) -> str:
        """One minimal call, to learn what this alias actually resolves to.

        A journal's header has to be truthful from its first line, and the only
        authority on what serves an alias is the server. Cheaper than being
        wrong about it for the length of a study.
        """
        return self.complete("Reply with: ok", "ok", max_tokens=1, temperature=0.0).served
