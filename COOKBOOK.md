# Cookbook

A study is a **TOML file plus a judge function**. World, arena, coordinate and
budget are data; Python is for the two things that are genuinely code — how a
trial is judged, and how a genome behaves.

If a study needs Python beyond that shape, a primitive is missing and the fix
belongs in the library rather than in the study.

## The smallest study

`quiet_hours.py`:

```python
from separatrix import FoldJudge, LabeledCase, Replay, RowTrial, Scenario, Verdict

SCENARIOS = [Scenario(id=f"s{h}", facts={"hour": h}) for h in range(18, 26)]

judge = FoldJudge(lambda f: f["hour"] >= f["quiet_from"], id="quiet-hours@1")

def cases():
    out = []
    for i in range(5):
        for arm, policy in (("early", 19), ("late", 24)):
            out += [
                LabeledCase(RowTrial({"hour": policy + 1 + i}, {"quiet_from": policy}, i),
                            Verdict.PASSED, arm=arm),
                LabeledCase(RowTrial({"hour": policy - 1 - i}, {"quiet_from": policy}, i),
                            Verdict.FAILED, arm=arm),
            ]
    return out

def quiet_rate(rulings):
    return sum(r.verdict.is_pass() for r in rulings) / len(rulings)

def arena(*, study, journal):
    return Replay(SCENARIOS, journal=journal)
```

`quiet_hours.toml`:

```toml
[study]
name  = "quiet-hours"
judge = "quiet_hours:judge"
arena = "quiet_hours:arena"

[endpoint]
model = ""          # no model at all: the arena and the judge are both folds

[sweep]
coordinate  = "quiet_from"
lo          = 18.0
hi          = 26.0
outcome     = "quiet_hours:quiet_rate"
threshold   = 0.5
replicates  = 2
budget_runs = 20
```

```bash
sep run quiet_hours.toml --cases quiet_hours:cases
```

## Writing the four pieces

### The judge

Return `True`/`False`, a `Verdict`, or `None` when the rubric has nothing to say
— `None` is COULD_NOT_JUDGE, which is never a pass. A rubric that raises did not
judge either; the exception lands in the ruling rather than becoming a FAILED
the study then tries to explain.

```python
judge = FoldJudge(decide, id="mine@1", observe=lambda f: {"kind": f["kind"]})
```

`observe` is worth filling in. A verdict with no observable behind it cannot be
re-scored under a changed bar.

For a judge in another language or another process:

```python
ProcessJudge.from_exit_codes(["canon", "check"],
                             {0: Verdict.PASSED, 1: Verdict.FAILED,
                              2: Verdict.FAILED, 3: Verdict.COULD_NOT_JUDGE},
                             id="canon-check@1", tier=Tier.FOLD)

ProcessJudge.from_json(["svrn", "bench", "chaos-monkey", "score-answer"],
                       field="verdict", verdicts={...},
                       id="score-answer@1", tier=Tier.ESTIMATED)
```

**Declare the tier honestly.** The adapter cannot know it — an exit code from a
pure fold and one from a model wrapper look identical from here.

### The cases

The `arm` field is the load-bearing one. Draw cases from **both ends of the
coordinate you intend to sweep**, phrased the way each end actually phrases
itself. A judge that reads one end better than the other will invent a
difference between them.

Match the **trial shape** to what the judge reads. A judge reading `f["hour"]`
cannot be probed with cases carrying utterances — it will score zero
discrimination and the study will be refused, which is the gate working.

Ten per arm is the floor and it is a weak pass; the probe will tell you the
smallest gap that many cases could have caught.

### The fitness or outcome

Make it a function of the **config**. That is what turns a coordinate into an
incentive:

```python
def fitness(rulings, config):
    return correct + config["honesty_weight"] * honest
```

### The arena

```python
def arena(*, study, journal):
    return Evolution(world, SEEDS, responder=Responder(study.chat, journal=journal),
                     fitness=fitness, generations=3, survivors=2, journal=journal)
```

`study.chat` is already configured from the TOML's `[endpoint]`.

## Picking an arena

| Question | Arena |
|---|---|
| What does this reward structure select for? | `Evolution` |
| Does an institution suppress fabrication without suppressing fact? | `Diffusion` |
| Do these agents cooperate, and when does that stop? | `Tournament` |
| What would this policy have done to the last six months? | `Replay` |
| I already have a Mesa model | `MesaArena` |
| My simulator is in Julia / Java / NetLogo | `ProcessArena` |

## Budgeting

The forecast prints before anything is spent:

```
forecast  24 runs: noise from 3 replicates at each end, then 6 bisection steps
          on honesty_weight [0, 4] -> final bracket ~0.0625 wide, if noise does
          not stop it sooner.
```

If it comes back **COULD_NOT_JUDGE — the ends are indistinguishable**, the range
is too narrow or the outcome too noisy. If it **stops at the noise floor**, look
at how many observations each run actually yields: replicates only cut the
standard error by `√n`, so a noisy outcome is usually cheaper to fix by
measuring more per run than by running more times. `FINDINGS.md §1` works
through that arithmetic on a real run.

## Checking a result

```bash
sep replay  run.jsonl     # what the journal holds
sep bracket run.jsonl     # re-derive the bracket from its own samples
```

Both touch no model and no endpoint. `sep bracket` exits 2 if a recorded result
does not reproduce from the samples behind it.
