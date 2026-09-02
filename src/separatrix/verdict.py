# SPDX-License-Identifier: AGPL-3.0-or-later
"""Four verdicts, never two — at every scale.

A check has four outcomes, not two, and collapsing them is how a green result
comes to mean nothing:

    PASSED           ran, was judged, met the bar
    FAILED           ran, was judged, missed the bar
    COULD_NOT_JUDGE  ran, but the question was unanswerable — an empty
                     population, a judge that abstained, a rate that is NaN
    NEVER_RAN        did not execute — budget exhausted, skipped, errored out

The two absent verdicts are the load-bearing ones. An unjudgeable axis reported
as a pass is a claim nobody earned, and it **never rescues a failure**: that is
the one rule `combine` exists to enforce.

The same four apply to a trial, to a run, and to a sweep. A sweep that could not
resolve a boundary above its own noise floor reports COULD_NOT_JUDGE, not a
number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

__all__ = ["Verdict", "Ruling"]


class Verdict(Enum):
    PASSED = "passed"
    FAILED = "failed"
    COULD_NOT_JUDGE = "could_not_judge"
    NEVER_RAN = "never_ran"

    def is_pass(self) -> bool:
        """Only PASSED is a pass. Absence of a verdict is not one."""
        return self is Verdict.PASSED

    def is_judged(self) -> bool:
        """Did we actually get an answer, either way?"""
        return self in (Verdict.PASSED, Verdict.FAILED)

    @classmethod
    def combine(cls, verdicts: Iterable["Verdict"]) -> "Verdict":
        """Fold many verdicts into one.

        Precedence: FAILED > NEVER_RAN > COULD_NOT_JUDGE > PASSED. A failure
        dominates everything, so no amount of unjudgeable company rescues it.
        An empty set is NEVER_RAN — nothing ran, so nothing passed.
        """
        seen = set(verdicts)
        if not seen:
            return cls.NEVER_RAN
        for v in (cls.FAILED, cls.NEVER_RAN, cls.COULD_NOT_JUDGE):
            if v in seen:
                return v
        return cls.PASSED

    def __str__(self) -> str:
        return {
            Verdict.PASSED: "PASSED",
            Verdict.FAILED: "FAILED",
            Verdict.COULD_NOT_JUDGE: "COULD-NOT-JUDGE",
            Verdict.NEVER_RAN: "NEVER-RAN",
        }[self]


@dataclass(frozen=True)
class Ruling:
    """One judge's ruling on one trial.

    `facts` carries the properties the judge observed, not only the verdict it
    reached. A verdict with no observable behind it cannot be re-derived, argued
    with, or re-scored under a changed bar.
    """

    verdict: Verdict
    trial_id: str
    judge: str                                   # name@version
    facts: Mapping[str, Any] = field(default_factory=dict)
    note: str = ""                               # why, when the verdict is absent

    def as_row(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "trial_id": self.trial_id,
            "judge": self.judge,
            "facts": dict(self.facts),
            "note": self.note,
        }
