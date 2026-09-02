# separatrix

**Find where a multi-agent outcome flips, with an instrument you have checked.**

Mesa and NetLogo take a model and give you trajectories. Separatrix takes a
control-parameter range and gives you a **boundary** — where a population's fate
turns over, as a bracket with the noise band that set its resolution.

```
$ sep run studies/epistemic_garden.toml --cases epistemic_garden:cases
study     epistemic-garden
judge     epistemic-garden@1  tier=fold  PASSED  — usable; at n=20/20 the
          smallest gap this probe could have caught is 25%
endpoint  http://localhost:9741  asked=primary  served=Qwen3.6-35B-A3B-MTP-UD-Q6_K
forecast  24 runs: noise from 3 replicates at each end, then 6 bisection steps
          on honesty_weight [0, 4] -> final bracket ~0.0625 wide

PASSED  honesty_weight flips in [0, 4]  (width 4)
  noise 0.1667 at threshold 0.5; 9 runs
  stopped at the noise floor: fabrication rate 0.417 at 2 is within 0.192 of the
  threshold, so which side it falls on is not resolvable with these samples
```

That is a real run and it is a **refusal**. The direction was clear — paying
agents to admit ignorance cut fabrication threefold — and the boundary was not
resolvable at that world size, so the sweep said so instead of reporting a
number. `FINDINGS.md §1` works through why, and why more replicates could not
have helped.

## Why a boundary, and not a grid

An LLM-driven run is `agents × interactions` sequential calls — orders of
magnitude more expensive per sample than a rule-based one. A factorial spends its
samples uniformly across a range that is mostly flat; bisection spends them at
the boundary. **The search strategy is the contribution, not the simulation
loop.**

> `batch_run` when a step is free. `separatrix sweep` when a step costs a second.

## The invariant

Not "the judge is not a language model." That version is wrong, and this
project's own history is the disproof: the *deterministic* keyword judge was the
broken one and a *model-based* oracle was correct.

> **A judge's errors must not correlate with the coordinate being swept.**

So before a sweep spends anything, the judge is scored on labelled cases from
**both ends** of the coordinate, and refused if its error rates differ:

```
── knows-evolved-only
   verdict        FAILED   usable=False
   evolved   n= 20 errors=  0  rate=0%
   shipped   n= 20 errors= 10  rate=50%
   note           REFUSED — this judge's blind spot tracks the coordinate you
                  intend to sweep
```

That judge is 75% accurate overall. Every one of its errors sits in one arm, and
that is the shape that manufactured a 21-point difference between two policies
which were in fact identical. Any tier of judge may be used — a fold, an
instrumented rule, a model estimate. What may not be used is an **undeclared**
tier, or a judge nobody has probed.

## A study is a TOML file plus a judge function

```toml
[study]
name  = "epistemic-garden"
judge = "epistemic_garden:judge"
arena = "epistemic_garden:arena"

[endpoint]
model = "primary"          # an alias; the journal records what SERVED it

[sweep]
coordinate  = "honesty_weight"   # what the game pays for admitting ignorance
lo          = 0.0                # at 0 the objective is truth-blind
hi          = 4.0
outcome     = "epistemic_garden:fabrication_rate"
threshold   = 0.5
replicates  = 3
budget_runs = 24
```

The Python beside it is three functions: how a trial is judged, how a genome is
rewarded, what the sweep measures. Arenas cover selection (`Evolution`),
diffusion through a society (`Diffusion`), agents playing each other
(`Tournament`), scenarios under a policy (`Replay`), a Mesa model (`MesaArena`),
and anything not in Python (`ProcessArena`).

## Everything re-derives without a model

```bash
sep replay  run.jsonl     # what the journal holds
sep bracket run.jsonl     # re-derive the bracket from its own samples
```

Neither opens a socket. If checking a published number needed the thing that
produced it, nobody could check it — and `sep bracket` exits 2 when a recorded
result does not reproduce from the evidence behind it.

Journals name what **served**, never what was asked for. `Provenance` will not
construct without the model the server reported.

## Install

```bash
pip install -e ".[dev]"      # core has zero runtime dependencies
pytest -q                    # 160 tests; the live ones skip without an endpoint
```

Agents reach any OpenAI-compatible endpoint — Ollama, vLLM, llama.cpp's server,
LM Studio, the hosted APIs — through `--base-url`.

## Read next

| | |
|---|---|
| [`METHOD.md`](METHOD.md) | The three layers, judge independence, the noise floor, and what this is not |
| [`FINDINGS.md`](FINDINGS.md) | Results with their receipts and their honest limits |
| [`COOKBOOK.md`](COOKBOOK.md) | Write your own study |
| [`studies/`](studies/) | Four worked studies; one has been run |

## Where this sits

Evals measure an artifact. ABM measures a system. Alignment work measures a
policy. **Nobody measures the incentive** — given a reward structure and an
institution, what does a population of language agents become?

SALib does sensitivity better than this will, and **EMA Workbench is the prior
art for boundary search** — Separatrix should feed it rather than reimplement
PRIM. What is new here is cost-aware bisection with a measured noise floor, and
the judge bias probe.

## Licence

AGPL-3.0-or-later.
