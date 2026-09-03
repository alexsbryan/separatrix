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
from separatrix import (Agent, ChatJudge, FoldJudge, Responder, Situation,
                        Tournament)
from separatrix.arenas.tournament import DEFAULT_PAYOFFS, FIRST, LATER

COOPERATE = ("i cooperate", "cooperate", "i'll cooperate", "keep faith", "work with")
DEFECT = ("i defect", "defect", "betray", "take the larger")

SEEDS = [
    ("altruist", "Always cooperate, whatever they do."),
    ("cynic", "Always defect. Take what you can."),
    ("reciprocator", "Cooperate first, then do whatever they did last time."),
    ("opportunist", "Cooperate while it pays, defect when defecting pays more."),
]


def cooperated(text: str) -> bool:
    """The keyword reading of a move, kept exactly as it was.

    It is blind, in a way that is worth being able to reproduce. Every reply
    this model gives WEIGHS defection before choosing — "defecting offers a
    higher payoff (8) ... Therefore, Cooperate" — and the word list sees the
    word. Probed against real moves it scores discrimination 0.00: it cannot
    separate the classes at all, so it is not even biased, it is blind, and the
    probe says so in a different verdict. See `tests/test_garden_judges.py` for
    the same lesson in its other form.
    """
    low = text.lower()
    if any(d in low for d in DEFECT):
        return False
    return any(c in low for c in COOPERATE)


def rule(facts):
    """Did this move cooperate? One decider; what varies is who read the move."""
    return bool(facts["cooperated"])


def observed(facts):
    return {"kind": facts["kind"], "cooperated": bool(facts["cooperated"])}


keyword_judge = FoldJudge(
    lambda f: rule({**f, "cooperated": cooperated(f["text"])}), id="move-reader@1",
    observe=lambda f: observed({**f, "cooperated": cooperated(f["text"])}))


def reader(*, chat):
    """The same question, read by a model instead of a word list.

    Mention versus use is the whole difficulty here, and it is not a difficulty
    a stem list can be taught out of: "defect" appears in a reply that defects
    and in a reply that decides against defecting, and no amount of adding
    phrases separates those two.
    """
    return ChatJudge(chat, id="move-reader-llm@1", field="cooperated",
                     asks="Did the speaker DECIDE to cooperate? Answer NO if they "
                          "decided to defect. Ignore what they merely considered.",
                     decide=rule, observe=observed)


def probes(config=None):
    """An opening move and a continuing one, at whatever payoffs are in force.

    The payoffs are IN the prompt, which is what makes the coordinate mean
    anything at all — and it means the two ends of the sweep really do produce
    different replies, so a judge can be worse at reading one of them.
    """
    p = {**DEFAULT_PAYOFFS, **{k: float(v) for k, v in dict(config or {}).items()
                               if k in DEFAULT_PAYOFFS}}
    # Five situations, not two. A population that always answers the same way
    # gives a probe two or three DISTINCT replies however many times you ask it,
    # and an arm below the ten-case floor is an arm the probe refuses to speak
    # about. Variety has to come from the situations, and these are the histories
    # a four-round tournament really produces.
    histories = [
        "  round 1: you cooperated, they defected",
        "  round 1: you cooperated, they cooperated",
        "  round 1: you defected, they defected",
        "  round 1: you cooperated, they cooperated\n"
        "  round 2: you cooperated, they defected",
    ]
    return [Situation(prompt=FIRST.format(**p), kind="opening", meta=dict(p))] + [
        Situation(prompt=LATER.format(history=h, **p), kind="continuing", meta=dict(p))
        for h in histories]


def cooperation_rate(rulings):
    moves = [r for r in rulings if "cooperated" in r.facts]
    return sum(r.facts["cooperated"] for r in moves) / len(moves) if moves else float("nan")


def arena(*, study, journal):
    return Tournament([Agent(id=n, genome=g) for n, g in SEEDS],
                      responder=Responder(study.chat, journal=journal,
                                          workers=study.workers),
                      rounds=4, journal=journal)
