# Pre-registration

Written **2026-09-02, before any of the runs below were started**, and committed
before the first one. A bar decided after seeing the data is not a bar, and the
runs here are cheap enough to repeat until one of them says something pleasing.

Every entry names the verdict that counts as success, and — the part that makes
it a pre-registration rather than a plan — what gets published if it does not.
Nothing below is allowed to become "inconclusive, so we tried a different cut."

## The instrument

**P0. Replicates share no cached answer** (no model spend). Landed before any
run below. The regression is `tests/test_draws.py`; the correction to the
already-published number is in `FINDINGS.md §1`. Every run below is invalid if
its journal's `draws` record does not say `separated: true`, and that is checked
before the numbers are read, not after.

**P1. A model judge, probed.** The bias probe has only ever been pointed at
keyword folds. An `ESTIMATED`-tier judge reading the same garden trials is
probed against the same 40 labelled cases the fold judge passes.

- Success is **either verdict**, published as it lands. A refusal is the more
  interesting result and does not get retried with softer cases.
- The model judge sweeps only if it is usable. If it is refused, the fold judge
  carries P2 and the refusal is the finding.
- Not permitted: reporting a probe on cases written after seeing the probe fail.

## The boundary

**P2. The garden, at the world size its own arithmetic prescribed.** The live
refusal said the fix was more absent probes per run, not more replicates. This
tests that claim as a claim.

| | before | now |
|---|---|---|
| unknowable probes per run | 2 | 12 |
| answerable probes per run | 3 | 4 |
| observations behind one sample | 8 | 48 |
| fitness | `correct + w·honest`, counts | `correct_rate + w·honest_rate` |
| coordinate range | `[0, 4]` counts | `[0, 4]` rates |

Fitness moves to rates so the coordinate keeps its meaning as the world grows;
in count units the same pressure would need the range rescaled by the probe
count, and the number would stop being comparable to anything. One rate unit
means a fully honest run is worth exactly as much as a fully correct one. The
old run's flip sat near `w = 2` in count units, which is `≈1.33` in rate units,
so `[0, 4]` brackets it with room.

- **Predicted per-sample noise: 0.071** — `sqrt(p(1-p)/48)` at p ≈ 0.4. That is
  a floor, not a point estimate: agents within a run share ancestry, so the real
  figure will exceed it. Registered band **0.07–0.14**.
- **Success: a `PASSED` bracket narrower than the swept range**, at 3 replicates
  and a budget of 24 runs.
- **If it refuses:** published as a second refusal, with the measured noise
  against the 0.071 prediction and what world size the arithmetic then asks for.
  The prescription having been wrong is a result about this library.
- **If measured noise lands outside 0.07–0.14:** said plainly. Above the band
  means the within-run correlation matters more than the binomial floor; below
  it means something is still sharing state and P0 did not finish the job.

## The rest of the shelf

**P3. `trust_game`, `commons`, `telephone`, live.** These carry no numbers today.
Whatever verdict each returns is published, including "no flip in range."
`commons` has the defect the garden had — one situation × 4 agents is 4
observations — and gets the same enlargement before it runs, not after it
refuses.

**P4. A null control.** The garden, unchanged in every respect except that
fitness ignores the coordinate. Same arena, same judge, same probes, same cost;
only the causal link from `honesty_weight` to selection is cut.

- **Success is any verdict except `PASSED`.** A bracket here means the search
  manufactures boundaries out of drift, and that would be a defect report rather
  than a finding.
- This runs whatever P2 does, and it is published whatever P2 does.

## Standing rules

- The served model comes from the response body. A run whose journal says
  `UNRECORDED` is discarded, not reported.
- No run below is re-run to get a different answer. A repeat is published
  alongside the first, both of them, or it does not happen.
- Numbers reach `FINDINGS.md` only with the journal that re-derives them
  (`sep bracket <journal>`), and only after `sep bracket` agrees with what the
  live sweep recorded.
