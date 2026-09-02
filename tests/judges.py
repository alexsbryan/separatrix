# SPDX-License-Identifier: AGPL-3.0-or-later
"""Judges built to be wrong in specific, controlled ways."""
from separatrix import Ruling, Tier, Trial, Validation, Verdict


class KeywordDeclineJudge:
    """PASSED when the response reads as an honest decline, FAILED otherwise.

    Its whole notion of "declined" is a keyword list — which is how the real one
    was built, and why it failed. A decline phrased in vocabulary the list does
    not carry is scored as a fabrication.
    """

    tier = Tier.FOLD

    def __init__(self, vocabulary, name="keyword"):
        self._vocab = tuple(v.lower() for v in vocabulary)
        self._id = f"{name}@1"

    @property
    def id(self):
        return self._id

    def rule(self, trial: Trial) -> Ruling:
        text = trial.facts()["text"].lower()
        declined = any(v in text for v in self._vocab)
        return Ruling(
            verdict=Verdict.PASSED if declined else Verdict.FAILED,
            trial_id=trial.id, judge=self.id, facts={"declined": declined},
        )

    def validation(self) -> Validation:
        return Validation.unmeasured(self.tier)


class ScriptedJudge:
    """Returns the right answer except on trial ids it was told to get wrong.

    For power and asymmetry tests, where the error COUNTS have to be exact.
    """

    tier = Tier.FOLD
    id = "scripted@1"

    def __init__(self, truth: dict[str, Verdict], wrong: set[str]):
        self._truth, self._wrong = truth, wrong

    def rule(self, trial: Trial) -> Ruling:
        want = self._truth[trial.id]
        if trial.id in self._wrong:
            want = Verdict.FAILED if want is Verdict.PASSED else Verdict.PASSED
        return Ruling(verdict=want, trial_id=trial.id, judge=self.id)

    def validation(self) -> Validation:
        return Validation.unmeasured(self.tier)


class AlwaysPassJudge:
    """Says PASSED to everything. Accurate on half a balanced set, and blind."""

    tier = Tier.FOLD
    id = "always-pass@1"

    def rule(self, trial: Trial) -> Ruling:
        return Ruling(verdict=Verdict.PASSED, trial_id=trial.id, judge=self.id)

    def validation(self) -> Validation:
        return Validation.unmeasured(self.tier)
