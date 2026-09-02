# SPDX-License-Identifier: AGPL-3.0-or-later
"""The judge, and the thing that must be true of it.

The invariant is **not** "the judge is not a language model." That version is
wrong, and this project's own history is the disproof: in the directive-search
experiment the *deterministic* keyword judge was the broken one and the
*model-based* oracle was correct. The keyword list did not know one policy's
decline vocabulary but did know the other's caveat vocabulary, so its blind spot
correlated with the treatment and it manufactured a 21-point effect that was
entirely artifact.

The requirement is:

    **A judge's errors must not correlate with the coordinate being swept.**

Being a pure fold is the easiest way to get that. It is not the definition of
it, and any tier may be used. What may not be used is an *undeclared* tier, or a
judge nobody has probed for the bias that matters.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable

from .trial import Trial
from .verdict import Ruling, Verdict

__all__ = ["Tier", "LabeledCase", "BiasResult", "Validation", "Judge"]


class Tier(Enum):
    """How a judge reaches its ruling. Declared, never inferred."""

    FOLD = "fold"
    """Pure computation. A game payoff, a resource state, an exit code, the
    arithmetic difference of two logs. Cannot be persuaded, because nothing in
    it reads persuasion."""

    INSTRUMENTED = "instrumented"
    """Deterministic rules applied to retrieved ground truth. Reaches outside
    itself for evidence, but the decision on that evidence is fixed."""

    ESTIMATED = "estimated"
    """A model estimates the fields. Legitimate, and the strongest judge this
    project has ever used is one — but persuadable in principle, so its bias
    probe is the one that actually has to bite."""


@dataclass(frozen=True)
class LabeledCase:
    """A trial whose correct verdict is known, and which arm it came from.

    `arm` is the load-bearing field. Bias is only measurable against something,
    and the something is the coordinate you intend to sweep: label cases drawn
    from BOTH ENDS of it, then ask whether the judge is worse at one end.
    """

    trial: Trial
    expected: Verdict
    arm: str


@dataclass(frozen=True)
class BiasResult:
    """Whether the judge's errors correlate with the arm."""

    verdict: Verdict
    arms: Mapping[str, dict]          # arm -> {n, errors, error_rate}
    p_value: float | None             # Fisher exact, two-sided; None if not computed
    alpha: float
    note: str = ""

    @property
    def asymmetry(self) -> float | None:
        rates = [a["error_rate"] for a in self.arms.values() if a["n"]]
        return max(rates) - min(rates) if len(rates) >= 2 else None


@dataclass(frozen=True)
class Validation:
    """What is known about this judge as an instrument.

    `verdict` is four-valued like everything else. A judge that has never been
    probed is NEVER_RAN — not a pass, and not a failure either.
    """

    tier: Tier
    verdict: Verdict = Verdict.NEVER_RAN
    cases: int = 0
    discrimination: float | None = None       # Youden's J: 0 = blind, 1 = perfect
    bias: BiasResult | None = None
    measured_at: datetime | None = None
    note: str = "never probed"

    @classmethod
    def unmeasured(cls, tier: Tier) -> "Validation":
        return cls(tier=tier)

    def stamped(self) -> "Validation":
        return replace(self, measured_at=datetime.now(timezone.utc))

    def usable(self) -> bool:
        """May a sweep compute a bracket from this judge? Only on a pass."""
        return self.verdict.is_pass()

    def as_row(self) -> dict:
        return {
            "tier": self.tier.value,
            "verdict": self.verdict.value,
            "cases": self.cases,
            "discrimination": self.discrimination,
            "bias": None if self.bias is None else {
                "verdict": self.bias.verdict.value,
                "arms": dict(self.bias.arms),
                "p_value": self.bias.p_value,
                "alpha": self.bias.alpha,
                "asymmetry": self.bias.asymmetry,
                "note": self.bias.note,
            },
            "measured_at": None if self.measured_at is None else self.measured_at.isoformat(),
            "note": self.note,
        }


@runtime_checkable
class Judge(Protocol):
    """Rules on trials, and answers for its own fitness as an instrument."""

    @property
    def id(self) -> str:
        """name@version. Carried in every ruling and every journal line, so a
        result can always name the instrument that produced it."""

    @property
    def tier(self) -> Tier:
        ...

    def rule(self, trial: Trial) -> Ruling:
        ...

    def validation(self) -> Validation:
        """What is known about this judge. `Validation.unmeasured(tier)` is the
        honest answer before anyone has probed it."""
