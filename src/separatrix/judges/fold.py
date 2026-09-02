# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tier-FOLD reference judge: a pure function, adapted.

A fold is the easiest way to get judge independence, because nothing in a pure
function reads persuasion. It is not the only way and it is not what the
invariant asks for — see `judge.py` — but it is where most studies should start,
and it costs a lambda.

A note on lineage. The sandbox this project grew out of carried
`chaos_rubric.py`, a hand port of a production scorer, and the port drifted: its
row-level properties still matched a year later but its verdict layer went
two-valued where the original had grown a third, unjudgeable outcome. Nothing
anywhere would ever have said so.

Separatrix does not mirror anyone's scorer. A study writes the rubric it means,
declares it FOLD, and probes it; a study that wants a *production* bar reaches
that bar through `ProcessJudge`, where it stays the source of truth instead of
becoming a copy that rots. Four verdicts are part of the type here, so the
particular divergence that started this cannot silently come back.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ..judge import BaseJudge, Tier
from ..trial import Trial
from ..verdict import Ruling, Verdict

__all__ = ["FoldJudge"]

Decision = Verdict | bool | None


class FoldJudge(BaseJudge):
    """Wraps `facts -> Verdict | bool | None`.

    `True`/`False` mean PASSED/FAILED, and `None` means COULD_NOT_JUDGE — the
    verdict for "this rubric has nothing to say about this trial", which is the
    honest answer and is never a pass. A rubric may also return a `Verdict`
    directly when it wants to distinguish COULD_NOT_JUDGE from NEVER_RAN.
    """

    def __init__(
        self,
        decide: Callable[[Mapping[str, Any]], Decision],
        *,
        id: str,
        observe: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ):
        super().__init__(id=id, tier=Tier.FOLD)
        self._decide = decide
        self._observe = observe

    def rule(self, trial: Trial) -> Ruling:
        facts = trial.facts()
        try:
            decision = self._decide(facts)
        except Exception as exc:                      # a rubric that raised did not judge
            return Ruling(verdict=Verdict.COULD_NOT_JUDGE, trial_id=trial.id, judge=self.id,
                          note=f"rubric raised {type(exc).__name__}: {exc}")
        observed = dict(self._observe(facts)) if self._observe else {}
        if decision is None:
            return Ruling(verdict=Verdict.COULD_NOT_JUDGE, trial_id=trial.id, judge=self.id,
                          facts=observed, note="rubric abstained")
        verdict = decision if isinstance(decision, Verdict) else (
            Verdict.PASSED if decision else Verdict.FAILED)
        return Ruling(verdict=verdict, trial_id=trial.id, judge=self.id, facts=observed)
