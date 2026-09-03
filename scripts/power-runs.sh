#!/bin/bash
# PREREGISTRATION.md A14 — three runs at adequate power.
#
# Detached on purpose: launched with `setsid nohup ... </dev/null &` so it is
# not a child of any agent session and survives one ending. Journals and logs
# land in the repository, never in a temp directory.
#
#   setsid nohup bash scripts/power-runs.sh > power-runs.log 2>&1 </dev/null &
#
# The parameter changes are commands here rather than edits somebody has to
# reconstruct from a diff afterwards.
cd "$(dirname "$0")/.." || exit 2
export PYTHONPATH=src

log() { echo "[$(date -Is)] $*"; }
run() {   # run <study> <log-tag>
  log "START $1  -> $2.run.log"
  timeout 21600 python3 -m separatrix run "studies/$1.toml" > "$2.run.log" 2>&1
  log "END   $1  exit=$?"
  grep -E "^(PASSED|FAILED|COULD-NOT-JUDGE|NEVER-RAN)" "$2.run.log" || tail -3 "$2.run.log"
  echo
}

log "R1 — commons at the bar that means something (0.5), nine replicates"
python3 scripts/tune.py studies/commons.toml sweep threshold   0.5
python3 scripts/tune.py studies/commons.toml sweep replicates  9
python3 scripts/tune.py studies/commons.toml sweep budget_runs 90
run commons commons-a14-t050

log "R2 — commons at A11's bar (0.1875), same power"
python3 scripts/tune.py studies/commons.toml sweep threshold 0.1875
run commons commons-a14-t1875

log "R3 — telephone at sixteen rounds, six replicates"
python3 scripts/tune.py studies/telephone.toml config rounds       16
python3 scripts/tune.py studies/telephone.toml sweep  replicates   6
python3 scripts/tune.py studies/telephone.toml sweep  budget_runs  48
run telephone telephone-a14-r16

log "ALL DONE — re-derive every verdict with: sep bracket studies/<name>.jsonl"
