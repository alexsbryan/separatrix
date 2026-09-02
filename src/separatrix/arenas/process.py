# SPDX-License-Identifier: AGPL-3.0-or-later
"""Any simulator that is not Python, as an arena.

The same subprocess primitive as `judges/process.py`, pointed the other way. One
adapter carries NetLogo headless, Agents.jl, MASON, Repast and the next thing —
config in as JSON on stdin, behaviour out as JSONL on stdout. Writing bindings
for each would be four dependencies and four things to keep working.

**The simulator produces behaviour; the judge rules on it.** That separation is
the architecture, so this deliberately does NOT let a simulator emit verdicts. A
tool that both acts and grades itself is the arrangement judge independence
exists to forbid.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..journal import Journal
from ..judge import Judge
from ..trial import Trial, digest
from ..verdict import Ruling, Verdict

__all__ = ["RowTrial", "ProcessArena"]


@dataclass(frozen=True)
class RowTrial(Trial):
    """One row of a simulator's output, ready to be judged."""

    row: Mapping[str, Any]
    config: Mapping[str, Any]
    index: int = 0

    @property
    def id(self) -> str:
        return digest("row", dict(self.row), dict(self.config), self.index)

    def facts(self) -> Mapping[str, Any]:
        return {**dict(self.config), **dict(self.row)}


class ProcessArena:
    """Run an external simulator once per configuration."""

    def __init__(self, argv: Sequence[str], *, timeout: float = 300.0,
                 journal: Journal | None = None):
        self.argv = list(argv)
        self.timeout = timeout
        self.journal = journal

    def run(self, config: Mapping[str, Any], judge: Judge) -> Sequence[Ruling]:
        try:
            proc = subprocess.run(
                self.argv, input=json.dumps(dict(config)), capture_output=True,
                text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return self._absent(config, f"simulator timed out after {self.timeout}s")
        except (OSError, ValueError) as exc:
            return self._absent(config, f"could not run {self.argv[0]!r}: {exc}")

        if proc.returncode != 0:
            return self._absent(config, f"simulator exited {proc.returncode}: "
                                        f"{proc.stderr.strip()[:400]}")

        rulings: list[Ruling] = []
        for i, line in enumerate(proc.stdout.splitlines()):
            if not (line := line.strip()):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                return self._absent(config, f"stdout line {i + 1} is not JSON: {exc}")
            if not isinstance(row, dict):
                return self._absent(config, f"stdout line {i + 1} is not an object")
            rulings.append(judge.rule(RowTrial(row, config, i)))

        if not rulings:
            # A simulator that emitted nothing did not run a trial. Reporting
            # that as an empty pass is how a green result gets earned by nobody.
            return self._absent(config, "the simulator produced no rows")
        if self.journal:
            self.journal.note("simulation", argv=self.argv[0], rows=len(rulings),
                              **{k: v for k, v in config.items()})
        return rulings

    def _absent(self, config: Mapping[str, Any], note: str) -> list[Ruling]:
        if self.journal:
            self.journal.note("simulation_failed", argv=self.argv[0], note=note,
                              **{k: v for k, v in config.items()})
        return [Ruling(verdict=Verdict.COULD_NOT_JUDGE,
                       trial_id=digest("failed", dict(config)),
                       judge="(simulator)", note=note)]
