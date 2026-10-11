"""Collect runs/s*/result.json into labels_dev.json, labels_test.json and labels_excluded.json. Prints counts only."""
import json
import os

import scenarios as SC

ROOT = os.path.dirname(os.path.abspath(__file__))
out = {"dev": {}, "test": {}}
excl = {}
for s in SC.S:
    f = os.path.join(ROOT, "runs", f"s{s['id']}", "result.json")
    r = json.load(open(f)) if os.path.exists(f) else {"error": "not run"}
    if r.get("labels"):
        out[s["split"]][str(s["id"])] = r["labels"]
    else:
        excl[str(s["id"])] = {"split": s["split"], "error": r.get("error")}
for split, labs in out.items():
    json.dump(labs, open(os.path.join(ROOT, f"labels_{split}.json"), "w"), indent=1, sort_keys=True)
    n = len(labs)
    pos = {k: sum(v[k] for v in labs.values()) for k in ("lost", "down", "exposed", "failed")}
    ctl = sum(not (v["lost"] or v["down"] or v["exposed"]) for v in labs.values())
    print(f"{split}: {n} labelled, positives {pos}, controls {ctl}")
json.dump(excl, open(os.path.join(ROOT, "labels_excluded.json"), "w"), indent=1)
print("excluded:", {k: (v["split"], (v["error"] or "")[:120]) for k, v in excl.items()})
