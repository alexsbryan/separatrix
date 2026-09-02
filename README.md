# separatrix

**Pre-alpha. Phase 1 of the plan, and nothing more.** The sweep does not exist
yet. What is here is the layer everything else depends on: what gets judged, the
four verdicts, and the probe that decides whether a judge may be trusted to
answer the question you are about to ask it.

Mesa and NetLogo take a model and give you trajectories. Separatrix takes a
control-parameter range and gives you a **boundary** — where a population's fate
flips, as a bracket with the noise band that sets its resolution. That shape
exists because an LLM-driven generation costs orders of magnitude more per
sample than a rule-based one, so the search strategy is the contribution rather
than the simulation loop.

## The invariant

Not "the judge is not a language model." That version is wrong, and this
project's own history is the disproof.

> **A judge's errors must not correlate with the coordinate being swept.**

In the experiment that founded this library, a *deterministic* keyword judge was
the broken one and a *model-based* oracle was correct. The keyword list did not
know one policy's decline vocabulary but did know the other's caveat vocabulary.
Its blind spot tracked the treatment, and it produced a 21-point difference
between two policies the real oracle showed were identical.

Any tier of judge may be used — a fold, an instrumented rule, a model estimate.
What may not be used is an undeclared tier, or a judge nobody has probed.

```
── knows-evolved-only
   verdict        FAILED   usable=False
   discrimination 0.50   cases=40   tier=fold
   evolved   n= 20 errors=  0  rate=0%
   shipped   n= 20 errors= 10  rate=50%
   bias           errors correlate with the arm: evolved 0% vs shipped 50%, p=0.0004
   note           REFUSED — this judge's blind spot tracks the coordinate you intend to sweep
```

The probe returns four verdicts, not two, because a judge fails in more than one
way. Too blind to separate the classes at all is COULD_NOT_JUDGE — bias is not
measurable through a blindfold. Too few labeled cases is also COULD_NOT_JUDGE,
because a null at n=3 is a statement about the probe rather than the judge. And
a pass says what it is worth:

```
   bias  no asymmetry detected (gap 0%, p=1.000); at n=20/20 the smallest gap
         this probe could have caught is 25%
```

## Running it

Zero runtime dependencies, by design rule rather than by accident.

```bash
pip install -e ".[dev]"
pytest -q
```

## What exists

| | |
|---|---|
| `trial.py` | `Trial` — abstract, because a wrapped simulator emits a trajectory and not utterances. `Exchange` is the LLM-agent shape. Ids are content hashes. |
| `verdict.py` | Four verdicts. `combine` enforces the one rule they exist for: an unjudgeable result never rescues a failed one. |
| `judge.py` | `Tier` (fold / instrumented / estimated), `Validation`, `LabeledCase`, the `Judge` protocol. |
| `validate.py` | The bias probe. Fisher exact in exact rational arithmetic, Youden's J for discrimination, and the minimum detectable asymmetry so a pass is not hollow. Stdlib only. |

Not yet: the sweep, the arenas, the journal, the CLI, the reference judges.

## Licence

AGPL-3.0-or-later. See `LICENSE`.
