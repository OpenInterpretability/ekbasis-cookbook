"""Eval v2, step 2: the request files (no labels) and the label file, for the 582 items of the study."""
import glob, hashlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pr_study"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "migguard_ekbasis"))
import analysis as A
from ekbasis import migrations as M

study = {it["id"] for it in A.load_items(True)}
new = {}
for p in glob.glob(os.path.join(HERE, "data", "items", "*.jsonl")):
    for l in open(p):
        r = json.loads(l)
        new[f"{r['repo']}/{r['mig']}"] = r
ids = sorted(k for k in study if not new[k].get("excluded"))
for arm in ("a2", "a1"):
    with open(os.path.join(HERE, "data", f"requests_{arm}.jsonl"), "w") as f:
        for k in ids:
            r = new[k]
            qs = {"lost": M.Q_LOST, "fails": M.Q_FAILS}
            if not r["transaction"]:
                qs["half"] = M.Q_HALF
            f.write(json.dumps({"id": k, "state": r[f"state_{arm}"], "questions": qs}) + "\n")
with open(os.path.join(HERE, "data", "labels_v2.jsonl"), "w") as f:
    for k in ids:
        r = new[k]
        f.write(json.dumps({"id": k, "stratum": r["stratum"], "transaction": r["transaction"], "label": r["label"],
                            "label_tx": r["label_tx"], "label_product": r["label_product"]}) + "\n")
for fn in ("requests_a2.jsonl", "requests_a1.jsonl", "labels_v2.jsonl"):
    print(fn, hashlib.sha256(open(os.path.join(HERE, "data", fn), "rb").read()).hexdigest(), len(ids))
