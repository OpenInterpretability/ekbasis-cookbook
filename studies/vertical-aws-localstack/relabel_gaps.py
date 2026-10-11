"""Applies runner.replace_gaps to results labelled before it existed (it only adds down = true where the apply log
shows a same-name destroy-then-create whose destruction completed). Idempotent; records what it changed."""
import json
import os

import runner as R
import scenarios as SC

for s in SC.S:
    f = os.path.join(R.RUNS, f"s{s['id']}", "result.json")
    if not os.path.exists(f):
        continue
    r = json.load(open(f))
    if "labels" not in r:
        continue
    plan = json.load(open(os.path.join(R.RUNS, f"s{s['id']}", "plan.json")))
    gaps = R.replace_gaps(plan, r["apply_out"], s["probes"])
    r["replace_gaps"] = gaps
    r["down_probe"] = any(x > 0 for x in r["probe_fail"])
    new = r["down_probe"] or bool(gaps)
    if new != r["labels"]["down"]:
        print(f"s{s['id']}: down {r['labels']['down']} -> {new} (gap {gaps}) | {s['title']}")
        r["labels"]["down"] = new
    elif gaps:
        print(f"s{s['id']}: gap {gaps}, down already {new}")
    json.dump(r, open(f, "w"), indent=1, default=str)
