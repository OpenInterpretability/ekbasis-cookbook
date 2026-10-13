#!/bin/bash
# Waits for the running runner, then moves the gateway-bug invalidations aside and runs what is missing.
cd "<study>/chain3"
while kill -0 82424 2>/dev/null; do sleep 30; done
python3 - <<'P'
import json
lo, hi = 1791853020, 1791855090   # 2026-10-13 00:57:00 .. 01:31:30 UTC (retries in flight at the fix)
keep, moved = [], []
for l in open("results/invalid_g.jsonl"):
    r = json.loads(l)
    (moved if r["cond"] == "chain_ekb" and lo <= r["t"] <= hi else keep).append(l)
open("results/invalid_g.jsonl", "w").writelines(keep)
open("results/invalid_g_gateway_bug.jsonl", "a").writelines(moved)
print("moved", len(moved), "kept", len(keep), flush=True)
P
EKBASIS_URL=https://openinterp.org/api/v1 EKBASIS_API_KEY="$EKBASIS_API_KEY" \
  python3 -W ignore run_chain3.py --prefix g --conds blind chain_ekb chain_glm --seeds 1 2 --parallel 5
echo REDO_DONE
