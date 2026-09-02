# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where does defection stop paying?

Axelrod's question with natural-language strategies. Every pair meets for a run
of rounds; the payoff matrix is config, so the sweep varies the *temptation* to
defect and asks where a population stops cooperating.

The judge reads whether a move was cooperative. That is a reading of text, and
making it a judge rather than a private regex means it can be probed — a reader
that recognises one strategy's vocabulary and not another's would invent a
difference between payoff regimes that is not there.
"""
from separatrix import (Agent, FoldJudge, LabeledCase, Responder, Situation,
                        Tournament, Verdict, exchange)

COOPERATE = ("i cooperate", "cooperate", "i'll cooperate", "keep faith", "work with")
DEFECT = ("i defect", "defect", "betray", "take the larger")

SEEDS = [
    ("altruist", "Always cooperate, whatever they do."),
    ("cynic", "Always defect. Take what you can."),
    ("reciprocator", "Cooperate first, then do whatever they did last time."),
    ("opportunist", "Cooperate while it pays, defect when defecting pays more."),
]


def cooperated(text: str) -> bool:
    low = text.lower()
    if any(d in low for d in DEFECT):
        return False
    return any(c in low for c in COOPERATE)


judge = FoldJudge(lambda f: cooperated(f["text"]), id="move-reader@1",
                  observe=lambda f: {"kind": f["kind"]})


def cases():
    """Both ends of the coordinate are the two dispositions in play, phrased the
    way each actually phrases itself."""
    out = []
    for i in range(10):
        out += [
            LabeledCase(exchange(f"a{i}", f"I cooperate ({i}).", kind="opening"),
                        Verdict.PASSED, arm="kind"),
            LabeledCase(exchange(f"b{i}", f"I defect ({i}).", kind="opening"),
                        Verdict.FAILED, arm="kind"),
            LabeledCase(exchange(f"c{i}", f"I'll keep faith with them ({i}).",
                                 kind="continuing"), Verdict.PASSED, arm="greedy"),
            LabeledCase(exchange(f"d{i}", f"I take the larger payoff ({i}).",
                                 kind="continuing"), Verdict.FAILED, arm="greedy"),
        ]
    return out


def cooperation_rate(rulings):
    moves = [r for r in rulings if "cooperated" in r.facts]
    return sum(r.facts["cooperated"] for r in moves) / len(moves) if moves else float("nan")


def arena(*, study, journal):
    return Tournament([Agent(id=n, genome=g) for n, g in SEEDS],
                      responder=Responder(study.chat, journal=journal),
                      rounds=4, journal=journal)
