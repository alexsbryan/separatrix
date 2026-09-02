# SPDX-License-Identifier: AGPL-3.0-or-later
"""A chat endpoint that never leaves the process."""
from separatrix import Completion


class FakeChat:
    """Answers by rule, counts calls, and reports a served id you control."""

    def __init__(self, answer, *, served="fake-model-7B", model="primary",
                 temperature=0.8, max_tokens=512):
        self._answer = answer if callable(answer) else (lambda s, u: answer)
        self.served, self.model = served, model
        self.temperature, self.max_tokens = temperature, max_tokens
        self.calls: list[tuple[str, str]] = []

    def complete(self, system, user, **kw):
        self.calls.append((system, user))
        served = self.served(len(self.calls)) if callable(self.served) else self.served
        return Completion(text=self._answer(system, user), served=served)
