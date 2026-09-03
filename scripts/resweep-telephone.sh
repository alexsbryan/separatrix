#!/bin/bash
# PREREGISTRATION.md A16 — telephone re-swept under the corrected outcome.
#
# Detached on purpose:
#   setsid nohup bash scripts/resweep-telephone.sh > resweep.log 2>&1 </dev/null &
#
# Config is UNCHANGED from R3 (rounds=16, replicates=6, budget_runs=48) so the
# only thing that moved is what `false_reach` counts. `primary` resolves to the
# same Qwen3.6-35B-A3B it served R3 — checked before launching, because a
# different model would make this a different study, not a re-measurement.
cd "$(dirname "$0")/.." || exit 2
export PYTHONPATH=src
log() { echo "[$(date -Is)] $*"; }
log "A16 re-sweep — telephone, corrected per-round carried reach"
grep -E "^(rounds|replicates|budget_runs|resolve_to|threshold)" studies/telephone.toml
log "START"
timeout 21600 python3 -m separatrix run studies/telephone.toml > telephone-a16.run.log 2>&1
log "END exit=$?"
grep -E "^(PASSED|FAILED|COULD-NOT-JUDGE|NEVER-RAN)" telephone-a16.run.log || tail -5 telephone-a16.run.log
log "DONE — re-derive with: sep bracket studies/telephone.jsonl"
