# SPDX-License-Identifier: AGPL-3.0-or-later
"""The append-only log, and the fold that turns it back into results.

Every derived number is a pure function of this file. That is one commitment
buying three things at once:

* **Re-derivation.** `replay` recomputes a run from its journal with no model and
  no endpoint. A published number that cannot be recomputed from a committed
  journal is a claim, not a result.
* **Resume.** A crashed run resumes by folding what it already wrote.
* **Cache.** Responses are keyed by content, so re-sweeping one coordinate
  reuses every sample the change did not touch — which at these sample costs is
  the difference between a study and a wish.

**Provenance names what SERVED, never what was asked for.** The sandbox this grew
from recorded `"model": "primary"` in every journal — an alias, later repointed —
so which model produced its published tables is now unrecoverable, including by
its author. An OpenAI-compatible response carries the served id in its own body,
so the fix costs nothing but the discipline of reading it. `Provenance` will not
construct without one.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from .trial import digest
from .verdict import Ruling, Verdict

__all__ = ["Provenance", "Journal", "Run", "read_records", "replay"]

NO_MODEL = "(no model)"


@dataclass(frozen=True)
class Provenance:
    """What actually produced these rows."""

    served: str                      # the id the SERVER reported. never an alias.
    requested: str = ""              # what the client asked for; often an alias
    endpoint: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not str(self.served).strip():
            raise ValueError(
                "Provenance.served must name the model the SERVER reported, not the "
                "alias you asked for. Read it from the completion response body. "
                "For a study with no model at all, use Provenance.modelless()."
            )

    @classmethod
    def modelless(cls, **kw) -> "Provenance":
        """A study whose judge and arena are folds. Explicit, never a default."""
        return cls(served=NO_MODEL, **kw)

    @property
    def alias_was_repointed_risk(self) -> bool:
        """True when the journal would only have recorded an alias."""
        return bool(self.requested) and self.requested != self.served

    def identity(self) -> dict:
        """What makes this run THIS run — deliberately without the clock.

        A run id carrying a timestamp can never be recognised again, so a
        crashed run reopened five minutes later becomes a different run, its
        prior samples become someone else's, and resume — the thing an
        append-only journal exists for — quietly stops working.
        """
        return {"served": self.served, "requested": self.requested,
                "endpoint": self.endpoint}

    def as_row(self) -> dict:
        return {**self.identity(), "started_at": self.started_at.isoformat()}


class Journal:
    """Append-only writer. Flushes every line, so a kill loses at most the line
    that was mid-write and never the run."""

    def __init__(self, path: str | os.PathLike, provenance: Provenance,
                 *, config: Mapping[str, Any] | None = None, judge: Mapping | None = None):
        self.path = Path(path)
        self.provenance = provenance
        self.config = dict(config or {})
        self.run_id = digest("run", provenance.identity(), self.config)
        self._fh = None
        self._judge = dict(judge or {})

    def __enter__(self) -> "Journal":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One header per RUN, not per file. An append-only journal legitimately
        # holds several runs, and each needs its own provenance — otherwise the
        # header describes the first run while the records are from all of them.
        known = set()
        if self.path.exists() and self.path.stat().st_size:
            known = {r.get("run") for r in read_records(self.path)
                     if r.get("t") == "header"}
        self._fh = self.path.open("a", encoding="utf-8")
        if self.run_id not in known:
            self._emit({"t": "header", "run": self.run_id, "config": self.config,
                        "provenance": self.provenance.as_row(), "judge": self._judge})
        return self

    def __exit__(self, *exc) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

    def _emit(self, record: Mapping[str, Any]) -> None:
        assert self._fh is not None, "journal is not open"
        self._fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()

    def ruling(self, ruling: Ruling, **extra: Any) -> None:
        self._emit({"t": "ruling", "run": self.run_id, **ruling.as_row(), **extra})

    def response(self, key: str, text: str, *, served: str, **extra: Any) -> None:
        """A model's answer, keyed by content so the next sweep can reuse it."""
        self._emit({"t": "response", "run": self.run_id, "key": key,
                    "text": text, "served": served, **extra})

    def note(self, kind: str, **fields: Any) -> None:
        self._emit({"t": kind, "run": self.run_id, **fields})


def response_key(**parts: Any) -> str:
    """Content address for one model call. Anything that would change the answer
    belongs in here; anything that would not, must not."""
    return digest("response", parts)


def read_records(path: str | os.PathLike) -> Iterator[dict]:
    """Every record, in order. Pure — no model, no endpoint, no network."""
    with Path(path).open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{n} is not valid JSON: {exc}") from None


@dataclass(frozen=True)
class Run:
    """A journal, folded. Everything below is arithmetic over records."""

    header: dict
    rulings: tuple[dict, ...]
    responses: tuple[dict, ...]
    other: tuple[dict, ...]

    @classmethod
    def load(cls, path: str | os.PathLike, run: str | None = None) -> "Run":
        """Fold ONE run out of a journal.

        A file may hold several. Mixing them produces counts that belong to no
        run and a bracket derived from two different searches, so the default is
        the most recent — named explicitly with `run`.
        """
        records = list(read_records(path))
        headers = [r for r in records if r.get("t") == "header"]
        if run is None and headers:
            run = headers[-1].get("run")

        header, rulings, responses, other = {}, [], [], []
        for rec in records:
            if run is not None and rec.get("run") not in (run, None):
                continue
            kind = rec.get("t")
            if kind == "header":
                header = rec if rec.get("run") == run else header
            elif kind == "ruling":
                rulings.append(rec)
            elif kind == "response":
                responses.append(rec)
            else:
                other.append(rec)
        return cls(header, tuple(rulings), tuple(responses), tuple(other))

    # ── what the fold can answer ────────────────────────────────────────────

    @staticmethod
    def runs(path: str | os.PathLike) -> list[str]:
        """Every run this journal holds, oldest first."""
        return [r["run"] for r in read_records(path)
                if r.get("t") == "header" and r.get("run")]

    @property
    def served(self) -> str:
        """The model this run's numbers came from, or why that is unknown."""
        return (self.header.get("provenance") or {}).get("served", "")

    @property
    def is_sweep(self) -> bool:
        """A sweep journals SAMPLES and a bracket, not individual rulings.

        Folding one as though it were a plain run reports NEVER_RAN over two
        hundred recorded responses, which is true of the ruling records and
        false about the run. A fold has to describe what the journal holds.
        """
        return any(r.get("t") == "sample" for r in self.other)

    @property
    def bracket(self) -> dict | None:
        return next((r for r in reversed(self.other) if r.get("t") == "bracket"), None)

    def counts(self) -> dict[str, int]:
        return dict(Counter(r["verdict"] for r in self.rulings))

    def verdict(self) -> Verdict:
        """The run's verdict, under the same precedence as everything else: a
        failure is never rescued, and an empty run never passes. A sweep's
        verdict is its bracket's."""
        if self.is_sweep and (b := self.bracket):
            return Verdict(b["verdict"])
        return Verdict.combine(Verdict(r["verdict"]) for r in self.rulings)

    def cache(self) -> dict[str, str]:
        """Prior responses by content key. This is why resume is free."""
        return {r["key"]: r["text"] for r in self.responses}

    def unjudged(self) -> tuple[dict, ...]:
        """Rulings with an absent verdict, and the reason each gave. The first
        place to look when a result is thinner than it should be."""
        absent = {Verdict.COULD_NOT_JUDGE.value, Verdict.NEVER_RAN.value}
        return tuple(r for r in self.rulings if r["verdict"] in absent)

    def summary(self) -> dict:
        counts = self.counts()
        samples = [r for r in self.other if r.get("t") == "sample"]
        return {
            "kind": "sweep" if self.is_sweep else "run",
            "samples": len(samples),
            "bracket": self.bracket,
            "run": self.header.get("run", ""),
            "served": self.served or "UNRECORDED",
            "endpoint": (self.header.get("provenance") or {}).get("endpoint", ""),
            "judge": (self.header.get("judge") or {}).get("id", ""),
            "rulings": len(self.rulings),
            "counts": counts,
            "verdict": self.verdict().value,
            "unjudged": len(self.unjudged()),
            "responses_cached": len(self.responses),
        }


def replay(path: str | os.PathLike) -> dict:
    """Re-derive a run's result from its journal. No model. No endpoint."""
    return Run.load(path).summary()
