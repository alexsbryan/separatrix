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
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = ["Completion", "Chat", "ChatError", "strip_think", "retry_after",
           "UNREPORTED"]

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
    finish: str = ""                             # why the model stopped
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def cut_off(self) -> bool:
        """The server stopped this at the token limit, mid-sentence.

        Worth its own field because a truncated reply is not a short one. An
        agent three lines into "here is why the text does not say" that gets cut
        before it says so has not declined and has not answered, and scoring it
        as either invents an observation.
        """
        return self.finish == "length"


BUSY = (429, 503)
MAX_WAIT = 90.0


def retry_after(exc: urllib.error.HTTPError, body: str) -> float | None:
    """How long the server asked us to wait, or None if it did not ask.

    A server saying "queue position 3, about 40 seconds" has not failed and has
    not refused: it has told the client exactly what to do, and a client that
    reads that as an error throws away work that was going to succeed. Ten
    minutes of harvesting died this way once.

    The hint is honoured, not guessed at, and it is capped — a server asking for
    an hour is a server to give up on, and silently waiting an hour is worse
    than saying so.
    """
    if exc.code not in BUSY:
        return None
    try:
        hint = json.loads(body).get("retry_after_secs")
    except (json.JSONDecodeError, AttributeError, TypeError):
        hint = None
    if hint is None:
        hint = exc.headers.get("Retry-After") if exc.headers else None
    try:
        return min(float(hint), MAX_WAIT) if hint is not None else 1.0
    except (TypeError, ValueError):
        return 1.0


@dataclass
class Chat:
    """One endpoint, one requested model."""

    base_url: str = "http://localhost:9741"
    model: str = "primary"
    timeout: float = 120.0
    temperature: float = 0.8
    max_tokens: int = 512
    retries: int = 4          # only for a server that ASKED us to wait

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

        body = self._post(payload)

        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ChatError(f"no completion in the response: "
                            f"{json.dumps(body)[:400]}") from None

        # The whole reason this function exists in one place.
        served = str(body.get("model") or "").strip() or UNREPORTED
        try:
            finish = str(body["choices"][0].get("finish_reason") or "")
        except (KeyError, IndexError, TypeError):
            finish = ""
        return Completion(text=strip_think(text or ""), served=served,
                          finish=finish, raw=body)

    def _post(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """One request, waiting when and only when the server asks us to."""
        waited = 0
        while True:
            req = urllib.request.Request(
                self.endpoint, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                text = exc.read()[:400].decode("utf-8", "replace")
                pause = retry_after(exc, text)
                if pause is not None and waited < self.retries:
                    waited += 1
                    time.sleep(pause)
                    continue
                busy = f" after {waited} wait(s) it asked for" if waited else ""
                raise ChatError(f"{self.endpoint} returned {exc.code}{busy}: "
                                f"{text}") from None
            except (urllib.error.URLError, TimeoutError) as exc:
                raise ChatError(f"cannot reach {self.endpoint}: {exc}") from None
            except json.JSONDecodeError as exc:
                raise ChatError(f"{self.endpoint} did not return JSON: {exc}") from None

    def probe_served(self) -> str:
        """One minimal call, to learn what this alias actually resolves to.

        A journal's header has to be truthful from its first line, and the only
        authority on what serves an alias is the server. Cheaper than being
        wrong about it for the length of a study.
        """
        return self.complete("Reply with: ok", "ok", max_tokens=1, temperature=0.0).served
