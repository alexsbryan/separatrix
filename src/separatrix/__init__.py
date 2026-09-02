# SPDX-License-Identifier: AGPL-3.0-or-later
"""Separatrix — find where a multi-agent outcome flips.

Mesa and NetLogo take a model and give you trajectories. This takes a control
parameter range and gives you a **boundary**: where the population's fate flips,
as a bracket with the noise band that sets its resolution.

That shape exists because of a cost fact. An LLM-driven generation is
`agents x interactions` sequential network calls — orders of magnitude more
expensive per sample than a rule-based ABM. If samples were cheap you would run
a full factorial and plot it. They are not, so the search strategy is the
contribution: bisect toward the flip, report a bracket, never a point.

And a boundary is only locatable if the instrument does not move when the
subject does. See `judge.py` for what that means and `validate.py` for the check.
"""
from .judge import (BaseJudge, BiasResult, Judge, LabeledCase, Tier, Validated,
                    Validation)
from .journal import Journal, Provenance, Run, read_records, replay
from .judges import FoldJudge, Outcome, ProcessJudge
from .trial import Exchange, Response, Situation, Trial, digest, exchange
from .validate import (fisher_exact_2x2, min_detectable_asymmetry, probe, validate,
                       youden_j)
from .verdict import Ruling, Verdict

__version__ = "0.0.1"

__all__ = [
    "Verdict", "Ruling",
    "Trial", "Situation", "Response", "Exchange", "exchange", "digest",
    "Judge", "Tier", "Validation", "Validated", "LabeledCase", "BiasResult", "BaseJudge",
    "FoldJudge", "ProcessJudge", "Outcome",
    "Journal", "Provenance", "Run", "replay", "read_records",
    "validate", "probe", "fisher_exact_2x2", "youden_j", "min_detectable_asymmetry",
]
