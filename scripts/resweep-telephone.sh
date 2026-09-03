#!/bin/bash
# PREREGISTRATION.md A17 — telephone at the threshold A8's rule picks from the
# ends A16's run measured: (2.7395833 + 0.1979167) / 2 = 1.47.
#
#   setsid nohup bash scripts/resweep-telephone.sh > resweep.log 2>&1 </dev/null &
cd "$(dirname "$0")/.." || exit 2
export PYTHONPATH=src
log() { echo "[$(date -Is)] $*"; }
log "A17 — telephone at the re-picked threshold"
grep -E "^(rounds|replicates|budget_runs|resolve_to|threshold)" studies/telephone.toml
log "START"
timeout 21600 python3 -m separatrix run studies/telephone.toml > telephone-a17.run.log 2>&1
log "END exit=$?"
grep -E "^(PASSED|FAILED|COULD-NOT-JUDGE|NEVER-RAN)" telephone-a17.run.log || tail -5 telephone-a17.run.log
log "DONE"
