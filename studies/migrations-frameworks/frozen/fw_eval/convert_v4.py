"""Framework eval (v4): the requests the product sends (no labels) and the label file."""
import glob, hashlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "mgfw"))
from ekbasis import migrations as M
items = []
for p in sorted(glob.glob(os.path.join(HERE, "data", "items", "*.jsonl"))):
    for l in open(p):
        r = json.loads(l)
        r["id"] = f"{r['project']}/{r['path']}"
        items.append(r)
inc = [r for r in items if not r.get("excluded")]
with open(os.path.join(HERE, "data", "requests_v4.jsonl"), "w") as f:
    for r in inc:
        p = r["product"]
        if p["decided"]:
            continue
        qs = {"lost": M.Q_LOST, "fails": M.Q_FAILS}
        if not p["transaction"]:
            qs["half"] = M.Q_HALF
        f.write(json.dumps({"id": r["id"], "state": p["state"], "questions": qs}) + "\n")
with open(os.path.join(HERE, "data", "labels_v4.jsonl"), "w") as f:
    for r in inc:
        f.write(json.dumps({"id": r["id"], "project": r["project"], "framework": r["framework"], "path": r["path"],
                            "sha256": r["sha256"], "stratum": r["stratum"], "label": r["label"],
                            "decided": r["product"]["decided"]}) + "\n")
for fn in ("requests_v4.jsonl", "labels_v4.jsonl"):
    p = os.path.join(HERE, "data", fn)
    print(fn, hashlib.sha256(open(p, "rb").read()).hexdigest(), sum(1 for _ in open(p)))
