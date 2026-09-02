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
| `validate.py` | The bias probe. Fisher exact in exact rational arithmetic, Youden's J for discrimination, and the minimum detectable asymmetry so a pass is not hollow. Stdlib only. `probe()` pairs a judge with what it earned. |
| `judges/fold.py` | `FoldJudge` — a pure function, adapted. A rubric with nothing to say abstains, and abstention is not a pass. |
| `judges/process.py` | `ProcessJudge` — one subprocess adapter for every judge that is not Python. Exit-code shape (`canon check`: 0 supported, 1 conflicts, 2 unaddressed, 3 cannot judge) and JSON shape (`score-answer`). Declares its tier because it cannot know it. |
| `journal.py` | Append-only log; every derived number is a fold over it. `Provenance` will not construct without the model the **server** reported. |
| `sweep.py` | `Search` — the decider — plus `sweep` (pays for samples) and `bracket_from_records` (replays them free). Noise-floor bisection, cost forecast, `Bracket`. |
| `__main__.py` | `sep replay` and `sep bracket` — both re-derive with no model and no endpoint. |

Nothing here ever fails into a pass. A crash, a timeout, unparseable output, a
missing field, an exit code nobody mapped — each is COULD_NOT_JUDGE carrying the
reason, because the alternative is a green result nobody earned.

```
$ sep replay run.jsonl
run       492e3ead9d247556
served    Qwen3.6-35B-A3B-MTP-UD-Q6_K
judge     grounding-fold@1
rulings   9   cached responses 9
  passed           6
  failed           2
  could_not_judge  1
verdict   FAILED

1 ruling(s) reached no verdict:
     1x no evidence for this probe kind
```

Journals name what **served**, never what was asked for. The sandbox this grew
from recorded `"model": "primary"` in every run — an alias, later repointed — so
which model produced its published tables is now unrecoverable, including by its
author. An OpenAI-compatible response carries the served id in its own body, so
the fix costs nothing but the discipline of reading it, and `Provenance` will not
construct without one.

## The sweep

```
$ sep bracket run.jsonl
PASSED  x flips in [0.25, 0.5]  (width 0.25)
  noise 0.02066 at threshold 0.5; 20 runs
  stopped at the noise floor: outcome 0.518 at 0.375 is within 0.0207 of the
  threshold (per-sample noise 0.0207 over 4 replicates), so which side it falls
  on is not resolvable with these samples

re-derived from the journal's own samples; matches what was recorded
```

Three things that make this the product rather than a bisection routine.

**The noise floor sets the resolution, and the answer is never a point.** Noise
is measured first from replicates at both ends, and the search stops when the
midpoint can no longer be told from the threshold. The step that could not be
called does **not** narrow the bracket — bisection's invariant is that the
crossing lies in the current interval, and a midpoint you cannot place says
nothing about which half holds it. That run above spent 20 of a 400-run budget,
because the remaining 380 would have bought nothing.

**It forecasts before it spends.** `60 runs / ~7200 model calls: noise from 3
replicates at each end, then 18 bisection steps -> final bracket ~3.8e-06 wide,
if noise does not stop it sooner.`

**One decider, two drivers.** Bisection chooses during acquisition, so the
decision cannot be a fold applied afterwards. It is a state machine, driven once
by `sweep` (which pays per sample) and once by `bracket_from_records` (which
replays a journal for free). A second implementation would be a second answer to
"where is the boundary", and the journal would stop being able to speak for the
run. `sep bracket` reports a recorded result its own samples do not reproduce as
a mismatch, and exits 2.

Four verdicts here too. A boundary found is PASSED. Both ends on the same side
of the threshold is FAILED — a definite "not in this range", not an absent
answer. Noise larger than the effect, an unprobed judge, or `replicates < 2` is
COULD_NOT_JUDGE. A budget too small to measure noise is NEVER_RAN, and spends
nothing.

Not yet: the arenas.

## Licence

AGPL-3.0-or-later. See `LICENSE`.
