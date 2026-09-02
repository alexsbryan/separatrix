# Method

## The one job

```
(control parameter range)  ->  (where the population's fate flips,
                                as a bracket with a noise band)
```

Mesa and NetLogo take a model and give you trajectories. This takes a range and
gives a **boundary**. The difference exists because of a cost fact: an LLM-driven
run is `agents × interactions` sequential calls, orders of magnitude more
expensive per sample than a rule-based one. A factorial spends its samples
uniformly across a range that is mostly flat; bisection spends them at the
boundary. The two also produce different objects — a factorial gives a response
surface, this gives a boundary with a stated resolution.

## The invariant

Not "the judge is not a language model." That version is wrong, and this
project's own history is the disproof.

> **A judge's errors must not correlate with the coordinate being swept.**

In the experiment that founded this library, a *deterministic* keyword judge was
the broken one and a *model-based* oracle was correct. The keyword list did not
know one policy's decline vocabulary but did know the other's caveat vocabulary.
Its blind spot tracked the treatment, and it produced a 21-point difference
between two policies the real oracle showed were identical (bare-answer 22% → 0%,
pass 73% → 94%, p = 0.012 — all of it artifact).

Being a pure fold is the easiest way to get independence. It is not the
definition of it.

### Three tiers, declared

| Tier | What it is | Examples |
|---|---|---|
| `FOLD` | Pure computation; nothing in it reads persuasion | a game payoff, a resource state, an exit code, the arithmetic difference of two logs |
| `INSTRUMENTED` | Deterministic rules over retrieved ground truth | a checker that reads the source and applies fixed rules |
| `ESTIMATED` | A model estimates the fields | a grounding oracle; the strongest judge this project has used |

Any tier is permitted. An **undeclared** tier is not, and neither is a judge
nobody has probed.

### The bias probe

Before a sweep spends anything, the judge is scored on labelled cases drawn from
**both ends** of the coordinate, and the sweep refuses if its error rates differ.
It is about fifty lines, it would have caught the founding failure before it
produced a single phantom point, and no ABM or eval framework ships it.

It returns four verdicts, because a judge fails in more than one way:

- **FAILED** — error rates differ by more than sampling explains (Fisher exact,
  two-sided, in exact rational arithmetic).
- **COULD_NOT_JUDGE, blind** — discrimination below the floor. Bias is not
  measurable through a blindfold, and that is a different failure with a
  different fix.
- **COULD_NOT_JUDGE, underpowered** — too few labelled cases. A null at n = 3 per
  arm describes the probe, not the judge.
- **PASSED** — and it says what the pass is worth: *"at n=20/20 the smallest gap
  this probe could have caught is 25%."* A pass at low power is a statement about
  the probe.

Discrimination is Youden's J, so a judge that always says the same thing scores
zero however accurate that makes it on a balanced set.

## Three layers

**Trial** is cheap, pure, deterministic. **Run** is expensive, stochastic,
model-driven. **Sweep** is many runs across one coordinate. Each layer's output
is the next layer's primitive.

### Layer 1 — the trial

`Trial` is abstract: an id and `facts()`. `Exchange` is the LLM-agent shape;
`(config, trajectory)` is a wrapped simulator's; `(scenario, decision)` is a
governance replay's. The tier system and the bias probe have nothing to do with
text, so they do not depend on the text-shaped concretion.

Four verdicts everywhere — PASSED, FAILED, COULD_NOT_JUDGE, NEVER_RAN — with one
rule they exist for: **an unjudgeable result never rescues a failed one.**
Precedence is `FAILED > NEVER_RAN > COULD_NOT_JUDGE > PASSED`, and an empty set
is NEVER_RAN, because nothing ran so nothing passed.

### Layer 2 — the run

`World` emits situations. An `Agent` is an identity and a genome that is a
sentence. A `Rule` turns verdicts into consequences. And:

> **A `Rule` may call a model. A `Judge` may not go unchecked.**

An institution with fallible judgment is realism — real governance runs on
fallible judgment. An unvalidated instrument is a broken experiment.

Arenas: `Evolution` (select and mutate), `Diffusion` (chains and an institution),
`Tournament` (agents playing each other), `Replay` (scenarios under a policy),
plus `MesaArena` and `ProcessArena` for simulators this project did not write.

### Layer 3 — the sweep

**The noise floor sets the resolution.** Noise is measured first from replicates
at both ends — pooled *within*-group, since pooling across two different means
would measure the effect and call it noise. The search stops when the midpoint
can no longer be told from the threshold, and **the step that could not be called
does not narrow the bracket**: bisection's invariant is that the crossing lies in
the current interval, and a midpoint you cannot place says nothing about which
half holds it.

**It forecasts before it spends.** `60 runs / ~7200 model calls: noise from 3
replicates at each end, then 18 bisection steps → final bracket ~3.8e-06 wide, if
noise does not stop it sooner.`

**One decider, two drivers.** Bisection chooses *during* acquisition, so the
decision cannot be a fold applied afterwards. It is a state machine, driven once
by `sweep` (which pays per sample) and once by `bracket_from_records` (which
replays a journal for free). A second implementation would be a second answer to
"where is the boundary", and the journal would stop being able to speak for the
run.

Replicates are **repeats, not seeds**. Where sampling happens server-side the
client cannot seed it, so a replicate varies the draw rather than controlling it.
That is what makes the noise real and worth measuring.

## Provenance

Every derived number is a pure fold over an append-only journal. `sep replay` and
`sep bracket` re-derive with **no model and no endpoint** — if checking a
published number needed the thing that produced it, nobody could check it.

`Provenance` will not construct without the model the **server** reported. Ask
for `primary`, record `Qwen3.6-35B-A3B-MTP-UD-Q6_K`. The alias is kept beside it
so a repoint is visible; an endpoint that changes model mid-run is journalled,
because a comparison spanning two models is not the comparison anyone thinks they
ran.

Run identity is deliberately **clock-free**. An id carrying a timestamp can never
be recognised again, so a crashed run reopened five minutes later becomes a
different run and resume quietly stops working.

## What this is not

Not a general ABM framework — Mesa exists. Not a general agent framework —
Concordia and LangGraph exist. Not a response-surface or sensitivity tool — SALib
does that better. **EMA Workbench is the prior art for boundary search**, with
PRIM and feature scoring; Separatrix should feed it rather than reimplement it.

What is new is cost-aware bisection with a measured noise floor, and the judge
bias probe.

## A constraint, stated rather than enforced

**No arena simulates identifiable people.** Agents act on text and situations,
never as stand-ins for named individuals. A simulation that produces a confident
artifact about a real person — *"the model says Dana will object"* — is a harm the
tooling should not make easy, whatever its accuracy.
