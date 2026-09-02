# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reference judges: a pure function, and everything that is not Python."""
from .fold import FoldJudge
from .process import Outcome, ProcessJudge

__all__ = ["FoldJudge", "ProcessJudge", "Outcome"]
