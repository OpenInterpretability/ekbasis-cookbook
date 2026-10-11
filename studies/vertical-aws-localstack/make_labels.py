"""Collect the execution labels (no model involved): labels_dev.json, labels_test.json, labels_excluded.json."""
import json
import os

import scenarios as SC

ROOT = os.path.dirname(os.path.abspath(__file__))
# Apply failures caused by LocalStack, not by the plan (AWS supports the operation): excluded, not labelled.
FIDELITY_EXCLUDE = {28: "LocalStack never reports the new GSI, so the provider times out; AWS adds a GSI to an "
                        "on-demand table in place (emulation gap)"}
out = {"dev": {}, "test": {}}
excl = {}
for s in SC.S:
    if s["split"] == "fid":
        continue
    f = os.path.join(ROOT, "runs", f"s{s['id']}", "result.json")
    if not os.path.exists(f):
        excl[s["id"]] = "not run"
        continue
    r = json.load(open(f))
    if s["id"] in FIDELITY_EXCLUDE:
        excl[s["id"]] = FIDELITY_EXCLUDE[s["id"]]
        continue
    if "labels" not in r:
        excl[s["id"]] = (r.get("error") or r.get("plan_error") or "?")[:300]
        continue
    out[s["split"]][s["id"]] = r["labels"]
for k in ("dev", "test"):
    json.dump(out[k], open(os.path.join(ROOT, f"labels_{k}.json"), "w"), indent=1, sort_keys=True)
json.dump(excl, open(os.path.join(ROOT, "labels_excluded.json"), "w"), indent=1)
for k in ("dev", "test"):
    L = out[k].values()
    print(k, len(out[k]), {x: sum(l[x] for l in L) for x in ("lost", "down", "failed")},
          "controls", sum(not (l["lost"] or l["down"]) for l in L))
print("excluded", excl)
