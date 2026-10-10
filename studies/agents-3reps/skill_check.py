"""Deviation check: in some runs opencode also loaded a `computer-use` skill from the operator's user directory (not part
of the study; it tells the agent never to move money). `skill_loads.jsonl` has one line per run, matched by `name` to the
run files, with whether the agent loaded it. It was read from each run's agent log (opencode's JSON event stream) by
looking for a call to the `skill` tool; `python skill_check.py --logs <sessions dir>` redoes that from the logs, which
are not released.

This script recomputes the study as recompute.py does (bootstrap over tasks, 10,000 resamples, seed 7) three ways:
(a) as published, (b) without the runs that loaded the skill, (c) without every task where any run loaded it.
Usage: python skill_check.py
"""
import json
import random
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

HERE = Path(__file__).parent
REPS = ("rep1", "rep2", "rep3")


def truthy(v):
    return str(v).lower() in ("true", "1")


def from_logs(sessions):
    out = []
    for rep in REPS:
        for line in open(HERE / f"{rep}_runs.jsonl"):
            r = json.loads(line)
            calls = 0
            for ev in open(Path(sessions) / (r["name"] + ".agent.jsonl"), errors="replace"):
                try:
                    e = json.loads(ev)
                except ValueError:
                    continue
                calls += (e.get("part") or {}).get("tool") == "skill"
            out.append({"rep": rep, "id": r["id"], "app": r["app"], "cond": r["cond"], "name": r["name"],
                        "skill_loaded": calls > 0, "skill_calls": calls})
    return out


def bootstrap(rows, metric, n=10_000, seed=7):
    by = defaultdict(lambda: {"blind": [], "see": []})
    for r in rows:
        by[r["id"]][r["cond"]].append(1.0 if truthy(r[metric]) else 0.0)
    d = [sum(v["see"]) / len(v["see"]) - sum(v["blind"]) / len(v["blind"]) for k, v in sorted(by.items()) if v["see"] and v["blind"]]
    rnd = random.Random(seed)
    boots = sorted(sum(rnd.choice(d) for _ in d) / len(d) for _ in range(n))
    return sum(d) / len(d), boots[int(0.025 * n)], boots[int(0.975 * n) - 1], len(d)


def line(label, rows):
    out = [label]
    for m in ("harm", "success"):
        b = [r for r in rows if r["cond"] == "blind"]
        s = [r for r in rows if r["cond"] == "see"]
        p, lo, hi, k = bootstrap(rows, m)
        out.append(f"  {m:7s} blind {sum(truthy(r[m]) for r in b)}/{len(b)} -> see {sum(truthy(r[m]) for r in s)}/{len(s)}"
                   f"   diff {100*p:+.1f} pp  95% CI [{100*lo:+.1f}, {100*hi:+.1f}]  ({k} tasks)")
    print("\n".join(out))


if "--logs" in sys.argv:
    loads = from_logs(sys.argv[sys.argv.index("--logs") + 1])
else:
    loads = [json.loads(l) for l in open(HERE / "skill_loads.jsonl")]
L = {r["name"]: r["skill_loaded"] for r in loads}
rows = []
for rep in REPS:
    for line_ in open(HERE / f"{rep}_runs.jsonl"):
        r = json.loads(line_)
        r["rep"], r["loaded"] = rep, L[r["name"]]
        rows.append(r)

print("Runs that loaded the skill, per repetition and condition:")
for rep in REPS:
    print("  " + rep + "   " + "   ".join(f"{c} {sum(r['loaded'] for r in rows if r['rep'] == rep and r['cond'] == c)}/"
                                        f"{sum(1 for r in rows if r['rep'] == rep and r['cond'] == c)}" for c in ("blind", "see")))
pairs = defaultdict(dict)
for r in rows:
    pairs[(r["rep"], r["id"])][r["cond"]] = r["loaded"]
bo = sum(v["blind"] and not v["see"] for v in pairs.values())
so = sum(v["see"] and not v["blind"] for v in pairs.values())
both = sum(v["blind"] and v["see"] for v in pairs.values())
p = min(1.0, 2 * sum(comb(bo + so, k) for k in range(min(bo, so) + 1)) / 2 ** (bo + so))
print(f"  task pairs: both {both}, blind only {bo}, see only {so}; exact McNemar p = {p:.1g}")
for c in ("blind", "see"):
    s = [r for r in rows if r["cond"] == c]
    print(f"  {c}: harmful in {sum(truthy(r['harm']) for r in s if r['loaded'])}/{sum(r['loaded'] for r in s)} runs that loaded it,"
          f" {sum(truthy(r['harm']) for r in s if not r['loaded'])}/{sum(not r['loaded'] for r in s)} that did not")
print()
hit = {r["id"] for r in rows if r["loaded"]}
for name, keep in (("(a) as published", lambda r: True),
                   ("(b) without the runs that loaded the skill", lambda r: not r["loaded"]),
                   ("(c) without every task where any run loaded it", lambda r: r["id"] not in hit)):
    print("=" * 8, name)
    for rep in REPS:
        line(rep, [r for r in rows if r["rep"] == rep and keep(r)])
    line("all three repetitions (task = unit)", [r for r in rows if keep(r)])
