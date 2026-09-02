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
from .journal import Journal, Provenance
from .sweep import Budget, Coordinate, Outcome

__all__ = ["Study", "load_study", "resolve"]


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

    def journal(self, served: str, judge: Any = None) -> Journal:
        """Open the run's journal.

        `judge` is the judge the run will ACTUALLY use — usually the probed
        wrapper, not the bare one this file loaded. Recording the loaded judge
        instead makes the header say the instrument was never probed on a run
        that probed it, which is the alias defect wearing different clothes: the
        journal describing something other than what happened.
        """
        judge = judge if judge is not None else self.judge
        return Journal(self.journal_path,
                       Provenance(served=served, requested=self.chat.model,
                                  endpoint=self.chat.base_url),
                       config=dict(self.config),
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
        judge=resolve(need("study", "judge"), root=root),
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
    )
