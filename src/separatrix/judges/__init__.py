# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reference judges: a pure function, a model, and everything that is not Python."""
from .chat import ChatJudge, read_yes_no
from .fold import FoldJudge
from .process import ProcessJudge, ProcessResult

__all__ = ["ChatJudge", "FoldJudge", "ProcessJudge", "ProcessResult", "read_yes_no"]
