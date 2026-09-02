# SPDX-License-Identifier: AGPL-3.0-or-later
"""What gets judged.

A `Trial` is the unit a judge rules on, and it is deliberately abstract. The
LLM-agent shape is an `Exchange` — a situation and the response an agent gave to
it. A wrapped simulator's shape is a config and the trajectory it produced. A
governance replay's shape is a scenario and the decision a policy reached.

The tier system and the bias probe have nothing to do with text, so they must
not depend on the text-shaped concretion. An earlier draft of this library had
`Judge.rule(Situation, Response)` and would have forced every non-conversational
simulator through a hole it does not fit.

Ids are content hashes. Nothing is identified by a counter, an address, or the
order it happened to arrive in.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

__all__ = ["digest", "Trial", "Situation", "Response", "Exchange"]


def digest(*parts: Any) -> str:
    """A stable content hash. Canonical JSON so key order never changes the id."""
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@runtime_checkable
class Trial(Protocol):
    """The thing a judge rules on."""

    @property
    def id(self) -> str:
        """Content hash of everything that produced this trial."""

    def facts(self) -> Mapping[str, Any]:
        """What a judge is allowed to read. A judge that needs something not in
        here is reading state it should not have."""


@dataclass(frozen=True)
class Situation:
    """What an agent was asked, and what a grounded answer may draw on."""

    prompt: str
    evidence: Sequence[str] = ()
    kind: str = "unspecified"
    meta: Mapping[str, Any] = field(default_factory=dict)
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(
                self, "id", digest("situation", self.prompt, list(self.evidence), self.kind)
            )
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True)
class Response:
    """What an agent said, and which agent said it."""

    text: str
    by: str = "anonymous"
    situation_id: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(
                self, "id", digest("response", self.text, self.by, self.situation_id)
            )


@dataclass(frozen=True)
class Exchange:
    """The LLM-agent shape of a `Trial`: one situation, one response to it."""

    situation: Situation
    response: Response

    @property
    def id(self) -> str:
        return digest("exchange", self.situation.id, self.response.id)

    def facts(self) -> Mapping[str, Any]:
        return {
            "prompt": self.situation.prompt,
            "evidence": list(self.situation.evidence),
            "kind": self.situation.kind,
            "text": self.response.text,
            "by": self.response.by,
        }


def exchange(prompt: str, text: str, *, evidence: Sequence[str] = (),
             kind: str = "unspecified", by: str = "anonymous") -> Exchange:
    """Build an `Exchange` without assembling both halves by hand."""
    s = Situation(prompt=prompt, evidence=evidence, kind=kind)
    return Exchange(situation=s, response=Response(text=text, by=by, situation_id=s.id))
