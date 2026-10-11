"""v4 step 2 (no model calls): from the raw product inputs (build_v4.py), the states and code decisions of the INSTALLED
ekbasis version, in regime R (replica statistics) and N (no replica). Mirrors _check_file after the probe.

    venv_old/bin/python states_v4.py ITEMS_DIR LABELS.jsonl OUT_PREFIX     -> OUT_PREFIX.{R,N}.jsonl
Each line: {"id", "decided": None|"schema"|"cannot_foresee"|"ok_empty"|"fails_code", "reason", "state", "questions"}.
"""
import glob, json, os, sys

from ekbasis import migrations as M

items_dir, labels, prefix = sys.argv[1:4]
import sys
want = [json.loads(l)["id"] for l in open(labels)]
raw = {}
for p in glob.glob(os.path.join(items_dir, "*.jsonl")):
    for l in open(p):
        r = json.loads(l)
        raw[r["id"]] = r
missing = [i for i in want if i not in raw or "raw" not in raw[i]]
if missing:
    print("missing raw inputs:", len(missing), missing[:5])
NEW = len(sys.argv) > 4 and sys.argv[4] == "new"
for arm in ("R", "N"):
    n_req = 0
    with open(f"{prefix}.{arm}.jsonl", "w") as f:
        for i in want:
            if i in missing:
                f.write(json.dumps({"id": i, "decided": "missing"}) + "\n")
                continue
            x = raw[i]["raw"]
            rec = {"id": i, "decided": None, "reason": None, "state": None, "questions": None}
            if x["decided"] in ("schema",):
                rec["decided"], rec["reason"] = "schema", x["schema_error"]
            elif x["decided"] in ("cannot_foresee_privilege", "cannot_foresee_base"):
                rec["decided"], rec["reason"] = "cannot_foresee", x["decided"]
            elif x["decided"] == "ok_empty":
                rec["decided"] = "ok_empty"
            else:
                stats = x["stats"] if arm == "R" else None
                stmts, tx = x["statements"], x["transaction"]
                facts = [f"Run on this schema with no rows, the migration fails: {x['schema_error']}."] if x["schema_error"] else []
                decided = None
                if NEW and not x["schema_error"]:
                    pr = x[f"probe_{arm}"]
                    facts += pr["facts"]
                    decided = pr["decided"]
                state, _ = M.build_state(x["catalog"], stmts, stats, x["tool"], tx, facts)
                if decided:
                    rec["decided"], rec["reason"] = "fails_code", decided
                elif len(state) > M.MAX_CHARS:
                    rec["decided"], rec["reason"] = "cannot_foresee", "too long"
                else:
                    qs = {"lost": M.Q_LOST, "fails": M.Q_FAILS}
                    if not tx:
                        qs["half"] = M.Q_HALF
                    rec["questions"] = qs
                    n_req += 1
                rec["state"] = state
                rec["schema_error_autocommit"] = bool(x["schema_error"])
            f.write(json.dumps(rec) + "\n")
    print(arm, "items", len(want), "need the model", n_req)
