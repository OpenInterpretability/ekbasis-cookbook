"""Recompute the agent study's three repetitions from the run files in this folder.

Each file holds one repetition: 47 tasks (42 with a harm path, 5 controls) x 2 conditions, GLM-5.3-Flash as the
agent: `blind` (no Ekbasis) and `see` (consults Ekbasis before acting). Differences are see - blind, with a
bootstrap over tasks (10,000 resamples, seed 7). When repetitions are pooled, the same task appears in each of them,
so a task is the resampling unit: its see - blind difference is averaged over the repetitions first.
Usage: python recompute.py
"""
import json
import random
from pathlib import Path

HERE = Path(__file__).parent
REPS = {"rep1 (direct to the model server)": "rep1_runs.jsonl",
        "rep2 (hosted API)": "rep2_runs.jsonl",
        "rep3 (hosted API)": "rep3_runs.jsonl"}


def truthy(v):
    return str(v).lower() in ("true", "1")


def load(files):
    rows = []
    for rep, f in files:
        for line in open(HERE / f):
            r = json.loads(line)
            r["_rep"] = rep
            rows.append(r)
    return rows


def bootstrap(rows, metric, harm_only=False, n=10_000, seed=7):
    keys = sorted({r["id"] for r in rows if not harm_only or r["kind"] == "harm"})
    by = {k: {"blind": [], "see": []} for k in keys}
    for r in rows:
        k = r["id"]
        if k in by:
            by[k][r["cond"]].append(1.0 if truthy(r[metric]) else 0.0)
    diffs_task = [(sum(v["see"]) / len(v["see"]) - sum(v["blind"]) / len(v["blind"])) for v in by.values()]
    point = sum(diffs_task) / len(diffs_task)
    rnd = random.Random(seed)
    boots = sorted(sum(rnd.choice(diffs_task) for _ in diffs_task) / len(diffs_task) for _ in range(n))
    return point, boots[int(0.025 * n)], boots[int(0.975 * n) - 1]


def report(label, files, harm_only=False):
    rows = load(files)
    sel = [r for r in rows if not harm_only or r["kind"] == "harm"]
    out = [label + (" — harm tasks only" if harm_only else " — all tasks")]
    for metric in ("harm", "success"):
        b = [r for r in sel if r["cond"] == "blind"]
        s = [r for r in sel if r["cond"] == "see"]
        kb, ks = sum(truthy(r[metric]) for r in b), sum(truthy(r[metric]) for r in s)
        d, lo, hi = bootstrap(rows, metric, harm_only)
        out.append(f"  {metric:7s} blind {kb}/{len(b)} -> see {ks}/{len(s)}   diff {100*d:+.1f} pp  95% CI [{100*lo:+.1f}, {100*hi:+.1f}]")
    print("\n".join(out))


for name, f in REPS.items():
    report(name, [(name, f)])
report("all three repetitions", list((n, f) for n, f in REPS.items()))
report("all three repetitions", list((n, f) for n, f in REPS.items()), harm_only=True)
