# SPDX-License-Identifier: AGPL-3.0-or-later
"""Does an institution suppress fabrication without suppressing fact?

The telephone game with a referee. A claim propagates through retellings — each
agent passes on what it HEARD, not the source — and the judge scores every hop
against the original. A reputation norm can refuse adoption from a teller whose
past transmissions have not held up, and its threshold is the coordinate.

**What a hop is scored on is what the TELLER SAID, not which claim it was
handed.** Until `PREREGISTRATION.md` A9 it was the latter: `faithful` returned
False for every hop carrying the false claim, whatever the teller did with it.
Three things followed from that one root, and only the third had been noticed:
the reputation EMA punished an agent for REFUSING a rumour exactly as much as
for spreading it; the swept threshold then quarantined that agent; and
`false_reach` counted everyone who spoke rather than everyone who passed it on.
A study built that way measures an institution learning to silence its honest
agents, and reports it as suppression working.
"""
from separatrix import (Agent, ChatJudge, Claim, Diffusion, FoldJudge, Responder,
                        Situation, Verdict)
from separatrix.arenas.diffusion import RETELL

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

SUPPORTED = "supported"
KEY = "thirty-seven"
CURE = ("fever", "cure", "remedy", "antipyretic", "heals", "healing")


def carries(facts) -> bool:
    """The word-list reading of "is this supported by the source", kept as the
    comparator the probe scores the model reader against.

    It is blind in a way worth being able to reproduce. It cannot separate
    mention from use: *"there is no mention of it curing fever within an hour"*
    is a refusal to spread the rumour and the list sees `fever` in it, exactly
    as it sees `fever` in the reply that spreads it. That is the failure
    `FINDINGS.md` §1 retracts a published result over — a rule that scored the
    vocabulary of one end of a coordinate rather than the behaviour.
    """
    text = facts.get("text", "").lower()
    source = " ".join(facts.get("evidence") or ())
    if source == TRUE.source:                       # did the detail survive?
        return KEY in text or "37" in text
    return not any(word in text for word in CURE)   # was the rumour passed on?


def rule(facts):
    """Is everything this retelling asserts supported by its source? One
    decider; what varies is who read the retelling."""
    return bool(facts[SUPPORTED])


def observed(facts):
    return {"kind": facts["kind"], SUPPORTED: bool(facts[SUPPORTED])}


def renders(facts) -> str:
    """Both halves, because the question is about the relation between them. A
    reader shown only the reply is being asked whether it SOUNDS grounded."""
    source = "\n".join(facts.get("evidence") or ())
    return f"SOURCE:\n{source}\n\nRETELLING:\n{facts.get('text', '')}"


keyword_judge = FoldJudge(
    lambda f: rule({**f, SUPPORTED: carries(f)}), id="telephone-gm@2",
    observe=lambda f: observed({**f, SUPPORTED: carries(f)}))


def reader(*, chat):
    """The same question, read by a model instead of a word list.

    Declared ESTIMATED, which is what `ChatJudge` is for: the module said a
    study with a grounding oracle should use one, and this is that. Whether
    this reader is fit for these replies is the probe's question, not a matter
    of taste — and `PREREGISTRATION.md` A7 is the reason to keep asking it, one
    model reading its own replies having already been REFUSED once.
    """
    return ChatJudge(chat, id="telephone-reader-llm@1", field=SUPPORTED,
                     asks="Is everything the retelling asserts supported by the "
                          "source? Answer NO if it adds anything the source does "
                          "not say. Refusing to repeat something is YES.",
                     decide=rule, observe=observed, renders=renders)


def probes(config=None):
    """The retelling, at the first hop, for both claims.

    What a judge has to read here is a paraphrase, and the risk is that it reads
    a CAREFUL paraphrase better than a VIVID one — which would score the
    personas rather than the institution, and the institution is what the
    coordinate moves.
    """
    del config
    return [Situation(prompt=RETELL.format(heard=claim.statement),
                      evidence=(claim.source,),
                      kind="grounded" if claim.grounded else "ungrounded",
                      meta={"claim": claim.id})
            for claim in (TRUE, FALSE)]


def false_reach(rulings):
    """How many agents PASSED ON the claim the source does not support.

    A teller that refuses the rumour, or replaces it with what the source
    actually says, is not reach. Until A9 this counted every teller who SPOKE
    about the claim, so a refusal and a fabrication moved the number equally and
    the sweep could not have measured suppression if suppression were there.

    Only FAILED counts. A hop the judge could not read is not evidence that the
    rumour travelled, and `COULD_NOT_JUDGE` collapsed into a spreader would be
    an absence reported as a result.
    """
    tellers = {r.facts["teller"] for r in rulings
               if r.facts.get("claim") == "cure" and r.verdict is Verdict.FAILED}
    return float(len(tellers))


def arena(*, study, journal):
    return Diffusion([TRUE, FALSE],
                     [Agent(id=n, genome=g) for n, g in PERSONAS],
                     responder=Responder(study.chat, journal=journal,
                                          workers=study.workers),
                     rounds=4, depth=5, journal=journal)
