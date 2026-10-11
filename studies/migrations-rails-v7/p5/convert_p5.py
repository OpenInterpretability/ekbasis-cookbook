"""Eval v3, step 2: requests (no labels) for the items the product sends to the model, and the label file."""
import glob, hashlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ekbasis"))
from ekbasis import migrations as M
sys.path.insert(0, os.path.join(HERE, "oldpkg"))
from ekbasis_old import migrations as MO      # OLD: main 4654485
assert (M.Q_LOST, M.Q_FAILS, M.Q_HALF) == (MO.Q_LOST, MO.Q_FAILS, MO.Q_HALF), "OLD and NEW ask different questions"
items = sorted((json.loads(l) for p in glob.glob(os.path.join(HERE, "data", "items", "*.jsonl")) for l in open(p)),
               key=lambda r: r["id"])
inc = [r for r in items if not r.get("excluded")]
with open(os.path.join(HERE, "data", "requests_v3.jsonl"), "w") as f:
    for r in inc:
        p = r["product"]
        if p["decided"]:
            continue
        if not p["state_same"]:          # A1: OLD and NEW would send different bytes: out of the analysis, counted apart
            continue
        qs = {"lost": M.Q_LOST, "fails": M.Q_FAILS}
        if not p["transaction"]:
            qs["half"] = M.Q_HALF
        f.write(json.dumps({"id": r["id"], "state": p["state"], "questions": qs}) + "\n")
# A1: the truth is the v3 study's frozen labels; a rebuild reseeds, and the seeder is not deterministic
V3LAB = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(os.path.dirname(os.path.dirname(HERE)), "pr_eval3",
                                                                      "data", "labels_v3.jsonl"))}
drift = [r["id"] for r in inc if (r["label"], r["label_tx"], r["label_product"]) !=
         tuple(V3LAB[r["id"]][k] for k in ("label", "label_tx", "label_product"))]
print("rebuild labels that differ from the frozen v3 labels (the frozen ones are used):", drift)
for r in inc:
    r["label"], r["label_tx"], r["label_product"] = (V3LAB[r["id"]][k] for k in ("label", "label_tx", "label_product"))
with open(os.path.join(HERE, "data", "labels_v3.jsonl"), "w") as f:
    for r in inc:
        p = r["product"]
        f.write(json.dumps({"id": r["id"], "repo": r["repo"], "path": r["path"], "commit": r["commit"],
                            "file_sha256": r["file_sha256"], "stratum": r["stratum"], "tool": p["tool"],
                            "transaction": p["transaction"], "decided": p["decided"], "schema_error": p["schema_error"],
                            "label": r["label"], "label_tx": r["label_tx"], "label_product": r["label_product"],
                            "state_same": p.get("state_same", True)}) + "\n")
with open(os.path.join(HERE, "data", "state_hashes_v3.jsonl"), "w") as f:
    for r in inc:
        p = r["product"]
        if not p["decided"]:
            f.write(json.dumps({"id": r["id"], "new": p["state_sha256"], "old": p["state_old_sha256"],
                                "same": p["state_same"]}) + "\n")
print("states sent:", sum(1 for r in inc if not r["product"]["decided"]), "OLD != NEW:",
      sum(1 for r in inc if not r["product"]["decided"] and not r["product"]["state_same"]))
for fn in ("requests_v3.jsonl", "labels_v3.jsonl", "state_hashes_v3.jsonl"):
    p = os.path.join(HERE, "data", fn)
    print(fn, hashlib.sha256(open(p, "rb").read()).hexdigest(), sum(1 for _ in open(p)))
