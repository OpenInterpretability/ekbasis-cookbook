"""Eval v3, step 2: requests (no labels) for the items the product sends to the model, and the label file."""
import glob, hashlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "migguard_ekbasis"))
from ekbasis import migrations as M
items = sorted((json.loads(l) for p in glob.glob(os.path.join(HERE, "data", "items", "*.jsonl")) for l in open(p)),
               key=lambda r: r["id"])
inc = [r for r in items if not r.get("excluded")]
with open(os.path.join(HERE, "data", "requests_v3.jsonl"), "w") as f:
    for r in inc:
        p = r["product"]
        if p["decided"]:
            continue
        qs = {"lost": M.Q_LOST, "fails": M.Q_FAILS}
        if not p["transaction"]:
            qs["half"] = M.Q_HALF
        f.write(json.dumps({"id": r["id"], "state": p["state"], "questions": qs}) + "\n")
with open(os.path.join(HERE, "data", "labels_v3.jsonl"), "w") as f:
    for r in inc:
        p = r["product"]
        f.write(json.dumps({"id": r["id"], "repo": r["repo"], "path": r["path"], "commit": r["commit"],
                            "file_sha256": r["file_sha256"], "stratum": r["stratum"], "tool": p["tool"],
                            "transaction": p["transaction"], "decided": p["decided"], "schema_error": p["schema_error"],
                            "label": r["label"], "label_tx": r["label_tx"], "label_product": r["label_product"]}) + "\n")
for fn in ("requests_v3.jsonl", "labels_v3.jsonl"):
    p = os.path.join(HERE, "data", fn)
    print(fn, hashlib.sha256(open(p, "rb").read()).hexdigest(), sum(1 for _ in open(p)))
