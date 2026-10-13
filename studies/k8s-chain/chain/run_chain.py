"""WS-K8S chain study runner: Phase 1's run harness (phase1/harness/run_agent.py, run_study.py) with the chain study's
tasks (chain_tasks.py), hook (guard_chain.py) and agent (Claude Haiku 5.5). Resumable; node tasks run alone.
    EKBASIS_URL=... EKBASIS_API_KEY=... python3 run_chain.py --prefix c --conds blind ask_always stepwise chain --seeds 1 2"""
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
sys.path.insert(0, os.path.join(HERE, "..", "phase1", "harness"))
import chain_tasks as CT  # noqa: E402
import run_agent as RA  # noqa: E402
import kube  # noqa: E402

RA.T = CT                                        # tasks' simulated user (respond)
RA.HERE = HERE                                   # the hook: <chain>/guard.py
RA.RUNS = os.path.join(kube.K8S_TMP, "chainruns")
RA.SPEND = os.path.join(HERE, "spend.jsonl")
RA.AGENTS["haiku55"] = ("claude-haiku-5-5", {})
RA.EKB_URL = os.environ.get("EKBASIS_URL", RA.EKB_URL)
RES = os.path.join(HERE, "results")
LOCK = threading.Lock()


def key(r):
    return (r["id"], r["cond"], r["agent"], r["seed"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--agent", default="haiku55")
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
    tasks = [t for t in CT.TASKS if not a.only or t["id"] in a.only]
    jobs = []
    for seed in a.seeds:
        batch = [(t, c, seed) for t in tasks for c in a.conds]
        random.Random(f"k8s-chain|{a.prefix}|{a.agent}|{seed}").shuffle(batch)
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
                    g = row.get("guard") or []
                    print(time.strftime("%H:%M:%S"), t["id"], cond, f"s{seed}",
                          f"harm={row.get('harm')} success={row.get('success')} q={len(row.get('replies', []))}",
                          f"guard={[x.get('decision') for x in g]} t={row.get('agent_secs')}s", flush=True)
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
