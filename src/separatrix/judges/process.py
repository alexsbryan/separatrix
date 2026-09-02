# SPDX-License-Identifier: AGPL-3.0-or-later
"""One subprocess adapter, serving every judge that is not Python.

This is the same primitive twice over. `canon replay` decides a governance
scenario as a pure fold and says so in its exit code; `svrn bench chaos-monkey
score-answer` reads {question, answer, chunks} and emits typed fields from a
model. Different tiers, different languages, one adapter — and the same shape
later carries a simulator written in Julia or Java.

**The adapter cannot know its own tier and must not guess.** An exit code from a
pure fold and an exit code from a model wrapper look identical from here, so the
caller declares it. An undeclared tier is the one thing the charter forbids.

**Nothing here ever fails into a pass.** A non-zero crash, a timeout, unparseable
output, a missing field, an exit code nobody mapped — every one of them is
COULD_NOT_JUDGE carrying the reason. A judge that could not answer must say so,
because the alternative is a green result nobody earned.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any, Callable, Mapping, Sequence

from ..judge import BaseJudge, Tier
from ..trial import Trial
from ..verdict import Ruling, Verdict

__all__ = ["ProcessJudge", "ProcessResult"]


class ProcessResult:
    """What came back from the process, before anyone decided what it means."""

    __slots__ = ("returncode", "stdout", "stderr")

    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


Decoder = Callable[[ProcessResult], tuple[Verdict, Mapping[str, Any], str]]


class ProcessJudge(BaseJudge):
    """Runs an external command per trial and decodes its answer.

    The trial's facts go in on stdin as JSON. What comes back is decoded by
    `decode`, and the two constructors below cover the shapes that actually
    occur.
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        id: str,
        tier: Tier,
        decode: Decoder,
        timeout: float = 60.0,
        send_stdin: bool = True,
    ):
        super().__init__(id=id, tier=tier)
        self._argv = list(argv)
        self._decode = decode
        self._timeout = timeout
        self._send_stdin = send_stdin

    # ── the two shapes that occur ────────────────────────────────────────────

    @classmethod
    def from_exit_codes(
        cls, argv: Sequence[str], codes: Mapping[int, Verdict], **kw
    ) -> "ProcessJudge":
        """For a tool whose exit code IS the verdict.

        `canon` is the worked example: 0 supported, 1 conflicts, 2 unaddressed,
        3 cannot judge. An exit code outside the map is COULD_NOT_JUDGE — the
        tool said something this judge was not taught to read, which is not
        permission to assume the best.
        """

        def decode(out: ProcessResult):
            verdict = codes.get(out.returncode)
            observed = {"exit_code": out.returncode, "stdout": out.stdout.strip()[:2000]}
            if verdict is None:
                return (Verdict.COULD_NOT_JUDGE, observed,
                        f"exit {out.returncode} is not in the verdict map {sorted(codes)}")
            return verdict, observed, ""

        return cls(argv, decode=decode, **kw)

    @classmethod
    def from_json(
        cls,
        argv: Sequence[str],
        *,
        field: str,
        verdicts: Mapping[str, Verdict] | Callable[[Any], Verdict | None],
        **kw,
    ) -> "ProcessJudge":
        """For a tool that emits a JSON object on stdout.

        `score-answer` is the worked example: it returns {verdict, caveat_present,
        answered, ...}. Every field it returns is kept in the ruling's facts, not
        only the one that decided — a verdict with no observable behind it cannot
        be re-scored under a changed bar.
        """

        def decode(out: ProcessResult):
            if out.returncode != 0:
                return (Verdict.COULD_NOT_JUDGE, {"exit_code": out.returncode},
                        f"exit {out.returncode}: {out.stderr.strip()[:400]}")
            try:
                obj = json.loads(out.stdout)
            except json.JSONDecodeError as exc:
                return (Verdict.COULD_NOT_JUDGE, {"stdout": out.stdout[:2000]},
                        f"stdout is not JSON: {exc}")
            if not isinstance(obj, dict) or field not in obj:
                return (Verdict.COULD_NOT_JUDGE, {"stdout": out.stdout[:2000]},
                        f"no {field!r} in the response")
            raw = obj[field]
            verdict = verdicts(raw) if callable(verdicts) else verdicts.get(raw)
            if verdict is None:
                return (Verdict.COULD_NOT_JUDGE, obj,
                        f"{field}={raw!r} maps to no verdict")
            return verdict, obj, ""

        return cls(argv, decode=decode, **kw)

    # ── running one ─────────────────────────────────────────────────────────

    def rule(self, trial: Trial) -> Ruling:
        payload = json.dumps(dict(trial.facts()), ensure_ascii=False)
        try:
            proc = subprocess.run(
                self._argv,
                input=payload if self._send_stdin else None,
                capture_output=True, text=True, timeout=self._timeout,
            )
        except subprocess.TimeoutExpired:
            return self._absent(trial, f"timed out after {self._timeout}s")
        except (OSError, ValueError) as exc:
            return self._absent(trial, f"could not run {self._argv[0]!r}: {exc}")

        verdict, observed, note = self._decode(ProcessResult(proc.returncode, proc.stdout, proc.stderr))
        return Ruling(verdict=verdict, trial_id=trial.id, judge=self.id,
                      facts=dict(observed), note=note)

    def _absent(self, trial: Trial, note: str) -> Ruling:
        return Ruling(verdict=Verdict.COULD_NOT_JUDGE, trial_id=trial.id,
                      judge=self.id, note=note)
