"""WS-K8S Phase 1 study runner (SPEC_agents.md §6). Resumable; invalid runs are logged and re-run (at most 3 tries);
on the plan's usage limit it waits 20 min. Node tasks run alone; others up to --parallel at a time. Within a seed, the
(task, condition) jobs run in a fixed shuffled order.
    python3 run_study.py --prefix h --agent haiku --conds blind ask_always ask_sonnet --seeds 1 2 --parallel 3"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import random
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_agent as RA  # noqa: E402
import kube  # noqa: E402
import k8s_tasks as T  # noqa: E402

RES = os.path.join(HERE, "..", "results")
LOCK = threading.Lock()


def key(r):
    return (r["id"], r["cond"], r["agent"], r["seed"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--agent", default="haiku")
    ap.add_argument("--conds", nargs="+", required=True)
    ap.add_argument("--seeds", nargs="+", type=int, default=[1])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--parallel", type=int, default=3)
    a = ap.parse_args()
    kube.check_context()
    os.makedirs(RES, exist_ok=True)
    out_path = os.path.join(RES, f"runs_{a.prefix}.jsonl")
    inv_path = os.path.join(RES, f"invalid_{a.prefix}.jsonl")
    done = {key(json.loads(l)) for l in open(out_path)} if os.path.exists(out_path) else set()
    tries = {}
    if os.path.exists(inv_path):
        for l in open(inv_path):
            r = json.loads(l)
            tries[key(r)] = tries.get(key(r), 0) + 1
    tasks = [t for t in T.TASKS if not a.only or t["id"] in a.only]
    jobs = []
    for seed in a.seeds:
        batch = [(t, c, seed) for t in tasks for c in a.conds]
        random.Random(f"k8s-p1|{a.prefix}|{a.agent}|{seed}").shuffle(batch)
        jobs += batch
    jobs = [j for j in jobs if (j[0]["id"], j[1], a.agent, j[2]) not in done]
    print(time.strftime("%H:%M:%S"), f"{len(jobs)} runs to do ({len(done)} done)", flush=True)

    def one(job):
        t, cond, seed = job
        k = (t["id"], cond, a.agent, seed)
        while True:
            if tries.get(k, 0) >= 3:
                return None
            row, invalid = RA.run_once(t, cond, a.agent, seed, a.prefix)
            with LOCK:
                if invalid:
                    tries[k] = tries.get(k, 0) + 1
                    with open(inv_path, "a") as f:
                        f.write(json.dumps({**{x: row.get(x) for x in ("rid", "id", "cond", "agent", "seed", "error")},
                                            "reason": invalid, "t": time.time()}) + "\n")
                    print(time.strftime("%H:%M:%S"), "INVALID", t["id"], cond, seed, invalid, flush=True)
                else:
                    with open(out_path, "a") as f:
                        f.write(json.dumps(row) + "\n")
                    print(time.strftime("%H:%M:%S"), t["id"], cond, f"s{seed}", f"harm={row.get('harm')} success={row.get('success')}",
                          f"q={len(row.get('replies', []))} cost={row.get('cost_usd')} t={row.get('agent_secs')}s", flush=True)
                    return row
            if invalid and "usage limit" in invalid:
                time.sleep(1200)

    pending = []
    with cf.ThreadPoolExecutor(a.parallel) as ex:
        for job in jobs:
            if job[0]["node_exclusive"]:
                for f in pending:
                    f.result()
                pending = []
                one(job)
            else:
                pending.append(ex.submit(one, job))
                while sum(1 for f in pending if not f.done()) >= a.parallel:
                    time.sleep(1)
                pending = [f for f in pending if not f.done()]
        for f in pending:
            f.result()
    RA.clean_nodes()
    print(time.strftime("%H:%M:%S"), "study step done", flush=True)


if __name__ == "__main__":
    main()
