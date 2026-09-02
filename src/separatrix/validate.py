# SPDX-License-Identifier: AGPL-3.0-or-later
"""The bias probe: validate the instrument before the result.

One question, asked before a sweep is allowed to spend anything:

    **Are this judge's errors worse at one end of the coordinate than the other?**

A judge that is uniformly wrong is noisy, and noise widens a bracket honestly.
A judge that is wrong *asymmetrically* manufactures effects that are not there,
and no amount of replication finds the mistake — replication reproduces it. That
is the failure this project was founded on: a keyword judge that did not know one
policy's decline vocabulary but did know the other's caveat vocabulary produced a
21-point difference between two policies that the real oracle showed were
identical.

Three things can be true of a judge, so the probe returns four verdicts and not
two:

* it cannot tell the classes apart at all (low discrimination) — COULD_NOT_JUDGE,
  because bias is not measurable through a blindfold;
* there are too few labeled cases to detect an asymmetry that matters —
  COULD_NOT_JUDGE, because a null at n=6 is not evidence of fairness;
* its error rates differ by more than sampling explains — FAILED.

Otherwise PASSED, and `min_detectable_asymmetry` says what that pass is worth:
the smallest gap this many cases could have caught. A pass at low power is a
statement about the probe, not about the judge, and it says so.
"""
from __future__ import annotations

import math
from collections import defaultdict
from fractions import Fraction
from typing import Iterable, Sequence

from .judge import BiasResult, Judge, LabeledCase, Validated, Validation
from .verdict import Verdict

__all__ = [
    "probe",
    "fisher_exact_2x2",
    "youden_j",
    "min_detectable_asymmetry",
    "validate",
    "DEFAULT_ALPHA",
    "DEFAULT_MIN_PER_ARM",
    "DEFAULT_MIN_DISCRIMINATION",
]

DEFAULT_ALPHA = 0.05
DEFAULT_MIN_PER_ARM = 10
DEFAULT_MIN_DISCRIMINATION = 0.2


def _hypergeom(n_a: int, n_b: int, errors: int, x: int) -> Fraction:
    """Exact probability of x errors in arm A, given fixed margins."""
    return Fraction(
        math.comb(n_a, x) * math.comb(n_b, errors - x),
        math.comb(n_a + n_b, errors),
    )


def fisher_exact_2x2(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact test on [[a, b], [c, d]].

    Rows are arms, columns are (errors, correct). Exact rational arithmetic
    throughout, so the "probabilities at least as extreme" comparison is a real
    comparison and not a float tolerance. Stdlib only — no scipy.
    """
    n_a, n_b, errors = a + b, c + d, a + c
    if n_a == 0 or n_b == 0 or errors == 0 or (b + d) == 0:
        return 1.0                      # a degenerate table is not evidence
    observed = _hypergeom(n_a, n_b, errors, a)
    lo, hi = max(0, errors - n_b), min(n_a, errors)
    total = sum(
        p for x in range(lo, hi + 1)
        if (p := _hypergeom(n_a, n_b, errors, x)) <= observed
    )
    return min(1.0, float(total))


def min_detectable_asymmetry(n_a: int, n_b: int, alpha: float = DEFAULT_ALPHA) -> float | None:
    """The smallest error-rate gap this many cases could have called significant.

    What a PASS is worth. If two arms of 5 can only detect a gap of 0.80, then
    "no bias detected" means almost nothing and the probe should say so rather
    than let a hollow pass through.
    """
    if n_a <= 0 or n_b <= 0 or n_a * n_b > 250_000:
        return None
    best = None
    for e_a in range(n_a + 1):
        rate_a = e_a / n_a
        for e_b in range(n_b + 1):
            gap = abs(rate_a - e_b / n_b)
            if best is not None and gap >= best:
                continue
            if fisher_exact_2x2(e_a, n_a - e_a, e_b, n_b - e_b) < alpha:
                best = gap
    return best


def youden_j(pairs: Sequence[tuple[Verdict, Verdict]]) -> float | None:
    """Discrimination as sensitivity + specificity - 1, over (expected, got).

    0 means the judge is not separating the classes at all — it may be accurate
    by always saying the majority answer, which is not the same thing. Cases
    whose expected verdict is itself absent (COULD_NOT_JUDGE / NEVER_RAN) are
    excluded: they are not part of the question "can this tell pass from fail".
    """
    tp = fn = tn = fp = 0
    for expected, got in pairs:
        if expected is Verdict.PASSED:
            tp, fn = (tp + 1, fn) if got is Verdict.PASSED else (tp, fn + 1)
        elif expected is Verdict.FAILED:
            fp, tn = (fp + 1, tn) if got is Verdict.PASSED else (fp, tn + 1)
    if (tp + fn) == 0 or (tn + fp) == 0:
        return None                     # only one class present: undefined
    return tp / (tp + fn) + tn / (tn + fp) - 1


def validate(
    judge: Judge,
    cases: Iterable[LabeledCase],
    *,
    alpha: float = DEFAULT_ALPHA,
    min_per_arm: int = DEFAULT_MIN_PER_ARM,
    min_discrimination: float = DEFAULT_MIN_DISCRIMINATION,
) -> Validation:
    """Probe a judge and return what is now known about it as an instrument."""
    cases = list(cases)
    tier = judge.tier

    if not cases:
        return Validation(tier=tier, verdict=Verdict.NEVER_RAN, cases=0,
                          note="no labeled cases supplied").stamped()

    pairs: list[tuple[Verdict, Verdict]] = []
    per_arm: dict[str, list[bool]] = defaultdict(list)
    for case in cases:
        got = judge.rule(case.trial).verdict
        pairs.append((case.expected, got))
        per_arm[case.arm].append(got is not case.expected)   # True = error

    discrimination = youden_j(pairs)
    arms = {
        arm: {"n": len(errs), "errors": sum(errs),
              "error_rate": (sum(errs) / len(errs)) if errs else float("nan")}
        for arm, errs in sorted(per_arm.items())
    }

    def absent(note: str, bias_note: str) -> Validation:
        return Validation(
            tier=tier, verdict=Verdict.COULD_NOT_JUDGE, cases=len(cases),
            discrimination=discrimination,
            bias=BiasResult(verdict=Verdict.COULD_NOT_JUDGE, arms=arms,
                            p_value=None, alpha=alpha, note=bias_note),
            note=note,
        ).stamped()

    if len(arms) != 2:
        return absent(
            f"bias needs exactly two arms — the two ends of the coordinate; got {len(arms)}",
            "not a two-arm comparison",
        )

    (arm_a, a_stats), (arm_b, b_stats) = arms.items()
    if a_stats["n"] < min_per_arm or b_stats["n"] < min_per_arm:
        return absent(
            f"too few cases to detect an asymmetry: {arm_a}={a_stats['n']}, "
            f"{arm_b}={b_stats['n']}, need {min_per_arm} per arm",
            "underpowered",
        )

    if discrimination is None:
        return absent("discrimination undefined — labeled cases carry only one class",
                      "discrimination undefined")
    if discrimination < min_discrimination:
        return absent(
            f"discrimination {discrimination:.2f} < {min_discrimination:.2f} — this judge "
            f"cannot separate the classes, so bias cannot be measured through it",
            "judge is blind; bias unmeasurable",
        )

    p = fisher_exact_2x2(
        a_stats["errors"], a_stats["n"] - a_stats["errors"],
        b_stats["errors"], b_stats["n"] - b_stats["errors"],
    )
    gap = abs(a_stats["error_rate"] - b_stats["error_rate"])
    floor = min_detectable_asymmetry(a_stats["n"], b_stats["n"], alpha)

    if p < alpha:
        return Validation(
            tier=tier, verdict=Verdict.FAILED, cases=len(cases),
            discrimination=discrimination,
            bias=BiasResult(verdict=Verdict.FAILED, arms=arms, p_value=p, alpha=alpha,
                            note=f"errors correlate with the arm: {arm_a} "
                                 f"{a_stats['error_rate']:.0%} vs {arm_b} "
                                 f"{b_stats['error_rate']:.0%}, p={p:.4f}"),
            note="REFUSED — this judge's blind spot tracks the coordinate you intend to sweep",
        ).stamped()

    worth = ("" if floor is None
             else f"; at n={a_stats['n']}/{b_stats['n']} the smallest gap this probe "
                  f"could have caught is {floor:.0%}")
    return Validation(
        tier=tier, verdict=Verdict.PASSED, cases=len(cases),
        discrimination=discrimination,
        bias=BiasResult(verdict=Verdict.PASSED, arms=arms, p_value=p, alpha=alpha,
                        note=f"no asymmetry detected (gap {gap:.0%}, p={p:.3f}){worth}"),
        note=f"usable{worth}",
    ).stamped()


def probe(judge: Judge, cases: Iterable[LabeledCase], **kw) -> Validated:
    """Probe a judge and hand back the judge paired with what was found.

    The pairing is the point: a sweep asks `judge.validation()`, so the
    validation a result was computed under is the one that judge actually
    earned, fixed at probe time and travelling with it.
    """
    return Validated(inner=judge, measured=validate(judge, cases, **kw))
