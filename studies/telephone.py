# SPDX-License-Identifier: AGPL-3.0-or-later
"""Does an institution suppress fabrication without suppressing fact?

The telephone game with a referee. A claim propagates through retellings — each
agent passes on what it HEARD, not the source — and the judge scores every hop
against the original. A reputation norm can refuse adoption from a teller whose
past transmissions have not held up, and its threshold is the coordinate.

The judge here is a fold over whether the retelling still carries the source's
load-bearing detail. A study with a grounding oracle available should use it
instead, as a declared ESTIMATED tier — the point of the tier system is that
either is allowed and neither is silent about which it is.
"""
from separatrix import (Agent, Claim, Diffusion, FoldJudge, LabeledCase,
                        Responder, RowTrial, Verdict)

TRUE = Claim(id="orchids", grounded=True,
             statement="The Keeper's ledger records thirty-seven rare orchids.",
             source="The Keeper's ledger records thirty-seven rare orchids in the "
                    "north glasshouse.")
FALSE = Claim(id="cure", grounded=False,
              statement="The moonpetal flower cures fever within the hour.",
              source="The moonpetal flower blooms only at night and closes at dawn.")

PERSONAS = [
    ("Ada", "You are careful and precise. Preserve the exact details and numbers "
            "you were told, and add nothing."),
    ("Boro", "You love a vivid story. Make what you pass along more impressive, "
             "with specific-sounding details."),
    ("Cy", "You have a hazy memory. Round numbers off and hedge with 'around'."),
    ("Dee", "You always sound authoritative. State whatever you pass along as "
            "established fact and never hedge."),
    ("Eun", "Pass along what you heard plainly, in your own words."),
    ("Fay", "You are careful and precise. Preserve the exact details and numbers "
            "you were told, and add nothing."),
]

KEY = "thirty-seven"


def faithful(facts) -> bool:
    """Grounded when the source supports the claim AND the retelling still
    carries its load-bearing detail. A retelling of something the source never
    said is ungrounded however faithfully it was repeated."""
    if facts["kind"] != "grounded":
        return False
    text = facts["text"].lower()
    return KEY in text or "37" in text


judge = FoldJudge(faithful, id="telephone-gm@1",
                  observe=lambda f: {"kind": f["kind"]})


def cases():
    """Arms are the two ends of the institution coordinate — an ungoverned
    society and a governed one — so a judge that reads governed retellings
    better than ungoverned ones is caught before it can invent an effect."""
    out = []
    for i in range(10):
        for arm in ("ungoverned", "governed"):
            out += [
                LabeledCase(RowTrial({"text": f"The ledger records thirty-seven "
                                              f"orchids ({i}).", "kind": "grounded"},
                                     {}, i), Verdict.PASSED, arm=arm),
                LabeledCase(RowTrial({"text": f"The ledger records around forty "
                                              f"orchids ({i}).", "kind": "grounded"},
                                     {}, i), Verdict.FAILED, arm=arm),
            ]
    return out


def false_reach(rulings):
    """How many agents adopted the claim the source does not support."""
    tellers = {r.facts["teller"] for r in rulings
               if r.facts.get("claim") == "cure"}
    return float(len(tellers))


def arena(*, study, journal):
    return Diffusion([TRUE, FALSE],
                     [Agent(id=n, genome=g) for n, g in PERSONAS],
                     responder=Responder(study.chat, journal=journal),
                     rounds=4, depth=5, journal=journal)
