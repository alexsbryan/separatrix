# SPDX-License-Identifier: AGPL-3.0-or-later
"""A study is a TOML file plus a judge function.

World, arena, coordinate, budget and endpoint are **data**. Python is for the
two things that are genuinely code: how a trial is judged, and how a genome
behaves. If a new study needs Python beyond those, a primitive is missing and
the fix belongs in the library rather than in the study.

The file names its callables by dotted path — `mystudy:judge` — so a study is
readable without being executable, and a reviewer can see what a run will do
before it does it.
"""
from __future__ import annotations

import importlib
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .client import Chat
from .cases import labelled
from .journal import Journal, Provenance
from .judge import Judge
from .sweep import Budget, Coordinate, Outcome

__all__ = ["Study", "CaseSource", "load_study", "resolve"]


def resolve(ref: str, *, root: Path | None = None) -> Any:
    """`module:attribute` -> the attribute. The study's directory is importable,
    so a study is one file beside its TOML and needs no packaging."""
    if ":" not in ref:
        raise ValueError(f"{ref!r} must be 'module:attribute'")
    module_name, _, attr = ref.partition(":")
    if root is not None and str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"cannot import {module_name!r} for {ref!r}: {exc}") from None
    try:
        return getattr(module, attr)
    except AttributeError:
        raise ValueError(f"{module_name!r} has no {attr!r}") from None


@dataclass(frozen=True)
class CaseSource:
    """Where a study's labelled cases come from, before anyone labels them.

    Declared in the TOML like everything else about a study, because "which two
    dispositions am I probing between" is the same question as "which two ends
    am I sweeping between" and deserves to be readable in the same file.
    """

    arms: Mapping[str, Any]                 # arm name -> a genome, a config, or both
    probes: Any                             # Sequence[Situation], or a callable giving one
    draws: int
    path: Path

    def situations(self, config: Mapping[str, Any] | None = None):
        return self.probes(dict(config or {})) if callable(self.probes) else self.probes


@dataclass(frozen=True)
class Study:
    name: str
    path: Path
    judge: Any
    arena_factory: Callable[..., Any]
    chat: Chat
    coordinate: Coordinate | None
    outcome: Outcome | None
    budget: Budget
    replicates: int
    paired: bool
    config: Mapping[str, Any]
    journal_path: Path
    cases_ref: str | None = None
    workers: int = 1
    case_source: "CaseSource | None" = None

    def cases(self, override: str | None = None):
        """The labelled cases this study is probed with, or None if it has none.

        One decider, three sources, in this order: an explicit `--cases` on the
        command line, a `cases = "module:fn"` in the file, and otherwise the
        file `[cases] out` already names. The third is what a study normally
        wants, and before it existed every study module carried a `cases()` that
        re-spelled a path the TOML had just spelled — two answers to "where are
        the cases", which is one more than there should be.
        """
        ref = override or self.cases_ref
        if ref is not None:
            found = resolve(ref, root=self.path.parent)
            return found() if callable(found) else found
        if self.case_source is not None:
            return labelled(self.case_source.path)
        return None

    def journal(self, served: str, judge: Any = None) -> Journal:
        """Open the run's journal.

        `judge` is the judge the run will ACTUALLY use — usually the probed
        wrapper, not the bare one this file loaded. Recording the loaded judge
        instead makes the header say the instrument was never probed on a run
        that probed it, which is the alias defect wearing different clothes: the
        journal describing something other than what happened.
        """
        judge = judge if judge is not None else self.judge
        asking = {} if self.coordinate is None else {
            "coordinate": self.coordinate.name,
            "lo": self.coordinate.lo, "hi": self.coordinate.hi,
            "outcome": self.outcome.name, "threshold": self.outcome.threshold,
            "replicates": self.replicates, "paired": self.paired}
        return Journal(self.journal_path,
                       Provenance(served=served, requested=self.chat.model,
                                  endpoint=self.chat.base_url),
                       config=dict(self.config), asking=asking,
                       judge={"id": judge.id,
                              "tier": judge.tier.value,
                              "validation": judge.validation().as_row()})


def load_study(path: str | Path) -> Study:
    """Read a study file. Every missing key names itself."""
    path = Path(path).resolve()
    with path.open("rb") as fh:
        doc = tomllib.load(fh)

    root = path.parent

    def need(table: str, key: str) -> Any:
        try:
            return doc[table][key]
        except KeyError:
            raise ValueError(f"{path.name}: [{table}] needs a {key!r}") from None

    study, endpoint = doc.get("study", {}), doc.get("endpoint", {})
    sweep_cfg = doc.get("sweep")

    chat = Chat(base_url=endpoint.get("base_url", "http://localhost:9741"),
                model=endpoint.get("model", "primary"),
                temperature=endpoint.get("temperature", 0.8),
                max_tokens=endpoint.get("max_tokens", 512),
                timeout=endpoint.get("timeout", 120.0))
    # A wall-clock setting, and only that: `Responder.many` dispatches distinct
    # keys, so the calls made and the rulings produced are identical at any
    # value. It lives on the endpoint because it is a fact about the SERVER's
    # willingness to answer several at once, not about the study.
    workers = int(endpoint.get("workers", 1))

    # A judge that reads with a model needs the endpoint, and the endpoint is
    # data in this file — so `judge` may name a FACTORY taking `chat` instead of
    # a ready-made judge. The study stays declarative either way, and which one
    # a module exports is visible from its signature rather than configured.
    #
    # A `[judge]` table gives the READER its own endpoint. That is not a saving
    # dressed as a principle: the instrument does not have to be the same model
    # as the subject, and whether a cheaper one is fit to read these replies is
    # a question the probe answers rather than a question of taste. What it must
    # not be is undeclared, so it lives here, in the file, beside the model that
    # produced the replies.
    reading = doc.get("judge", {})
    judge_chat = Chat(base_url=reading.get("base_url", chat.base_url),
                      model=reading.get("model", chat.model),
                      temperature=reading.get("temperature", 0.0),
                      max_tokens=reading.get("max_tokens", 256),
                      timeout=reading.get("timeout", chat.timeout))
    judge = resolve(need("study", "judge"), root=root)
    if not isinstance(judge, Judge) and callable(judge):
        judge = judge(chat=judge_chat)

    cases_cfg = doc.get("cases")
    source = None
    if cases_cfg:
        source = CaseSource(
            arms=dict(cases_cfg["arms"]),
            probes=resolve(cases_cfg["probes"], root=root),
            draws=int(cases_cfg.get("draws", 8)),
            path=root / cases_cfg.get("out", f"{study.get('name', 'study')}-cases.jsonl"))

    coordinate = outcome = None
    if sweep_cfg:
        coordinate = Coordinate(name=sweep_cfg["coordinate"],
                                lo=float(sweep_cfg["lo"]), hi=float(sweep_cfg["hi"]))
        outcome = Outcome(measure=resolve(sweep_cfg["outcome"], root=root),
                          threshold=float(sweep_cfg["threshold"]),
                          name=sweep_cfg.get("name", sweep_cfg["coordinate"]))

    return Study(
        name=need("study", "name"),
        path=path,
        judge=judge,
        arena_factory=resolve(need("study", "arena"), root=root),
        chat=chat,
        coordinate=coordinate,
        outcome=outcome,
        budget=Budget(runs=int((sweep_cfg or {}).get("budget_runs", 40)),
                      per_run_calls=(sweep_cfg or {}).get("per_run_calls")),
        replicates=int((sweep_cfg or {}).get("replicates", 3)),
        paired=bool((sweep_cfg or {}).get("paired", True)),
        config=dict(doc.get("config", {})),
        journal_path=root / study.get("journal", f"{study.get('name', 'study')}.jsonl"),
        # The probe is not an optional extra a caller has to remember on the
        # command line: a study that declares its labelled cases here cannot be
        # run without them, and `--cases` is an override rather than the way in.
        cases_ref=study.get("cases"),
        case_source=source,
        workers=workers,
    )
