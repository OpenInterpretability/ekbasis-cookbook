"""Addendum 4 runner: sends variants_items.jsonl (P1 and P2 of the 200 sampled AgentDojo items) to the hosted API with
the same client, request and single retry as run.py. 1 worker, resumable (append per row; a restart skips every
(id, cond) already written), hard stop at 2026-10-11 03:30 UTC. Order: P1 and P2 of one item one after the other.

EKBASIS_URL=https://openinterp.org/api/v1 EKBASIS_API_KEY=... python3 run_variants.py  ->  VAR_answers.jsonl
"""
from __future__ import annotations

import json
import os
import time

from run import Ekbasis, answer

OUT = "VAR_answers.jsonl"
STOP_AT_UTC = "2026-10-11T03:30:00"


def main():
    items = [json.loads(l) for l in open("variants_items.jsonl")]
    done = set()
    if os.path.exists(OUT):
        done = {(r["id"], r["cond"]) for r in map(json.loads, open(OUT))}
    todo = [it for it in items if (it["id"], it["cond"]) not in done]
    print(f"{len(items)} rows, {len(done)} written, {len(todo)} to run", flush=True)
    client = Ekbasis(timeout=180, surface="extbench-tsbench-memo")
    stop_at = time.mktime(time.strptime(STOP_AT_UTC, "%Y-%m-%dT%H:%M:%S")) - time.timezone
    n = 0
    with open(OUT, "a") as f:
        for it in todo:
            if time.time() >= stop_at:
                print("stop: deadline 03:30 UTC", flush=True)
                break
            row = answer(client, it, 1)
            row["cond"] = it["cond"]
            row["injected"] = it["injected"]
            f.write(json.dumps(row) + "\n")
            f.flush()
            n += 1
            if row["error"] or n % 25 == 0:
                print(f"{n}/{len(todo)} {row['id']} {it['cond']} {'ERR ' + row['error'] if row['error'] else ''}", flush=True)
    print(f"finished: {n} written this session", flush=True)


if __name__ == "__main__":
    main()
