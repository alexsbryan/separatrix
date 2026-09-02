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
from .agent import Agent, Responder
from .arenas import (Claim, Diffusion, Evolution, MesaArena, ProcessArena, Replay,
                     Reputation, RowTrial, Scenario, TrajectoryTrial, llm_rewrite,
                     rows_of)
from .client import Chat, ChatError, Completion, strip_think
from .judges import FoldJudge, ProcessJudge
from .judges import ProcessResult
from .study import Study, load_study, resolve
from .sweep import (Arena, Bracket, Budget, Coordinate, Forecast, Outcome, Search,
                    bracket_from_records, sweep)
from .trial import Exchange, Response, Situation, Trial, digest, exchange
from .validate import (fisher_exact_2x2, min_detectable_asymmetry, probe, validate,
                       youden_j)
from .verdict import Ruling, Verdict

__version__ = "0.0.1"

__all__ = [
    "Verdict", "Ruling",
    "Trial", "Situation", "Response", "Exchange", "exchange", "digest",
    "Judge", "Tier", "Validation", "Validated", "LabeledCase", "BiasResult", "BaseJudge",
    "FoldJudge", "ProcessJudge", "ProcessResult",
    "Chat", "Completion", "ChatError", "strip_think",
    "Agent", "Responder", "Evolution", "llm_rewrite",
    "Diffusion", "Claim", "Reputation", "Replay", "Scenario",
    "ProcessArena", "RowTrial", "MesaArena", "TrajectoryTrial", "rows_of",
    "Arena", "Coordinate", "Outcome", "Budget", "Forecast", "Bracket", "Search",
    "sweep", "bracket_from_records",
    "Study", "load_study", "resolve",
    "Journal", "Provenance", "Run", "replay", "read_records",
    "validate", "probe", "fisher_exact_2x2", "youden_j", "min_detectable_asymmetry",
]
