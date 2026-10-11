"""T2, passo 2 (sem modelo): estados e decisões em código do ekbasis INSTALADO no PYTHONPATH, regimes R e N.
    PYTHONPATH=ekbasis_old python3 states_t2.py data/items_t2 LABELS data/st_old
    PYTHONPATH=ekbasis     python3 states_t2.py data/items_t2 LABELS data/st_new
Cada linha: {"id", "decided", "reason", "state", "questions", "notes", "schema_error_autocommit"}."""
import glob, json, os, sys
from ekbasis import migrations as M

items_dir, labels, prefix = sys.argv[1:4]
print("ekbasis from", os.path.dirname(M.__file__), "cut" if hasattr(M, "schema_cut") else "no cut")
want = [json.loads(l)["id"] for l in open(labels)]
raw = {}
for p in glob.glob(os.path.join(items_dir, "*.jsonl")):
    for l in open(p):
        r = json.loads(l)
        raw[r["id"]] = r
for arm in ("R", "N"):
    n_req = 0
    with open(f"{prefix}.{arm}.jsonl", "w") as f:
        for i in want:
            x = raw[i]["raw"]
            rec = {"id": i, "decided": None, "reason": None, "state": None, "questions": None, "notes": []}
            if x["decided"] == "schema":
                rec["decided"], rec["reason"] = "schema", x["schema_error"]
            elif x["decided"] in ("cannot_foresee_privilege", "cannot_foresee_base"):
                rec["decided"], rec["reason"] = "cannot_foresee", x["decided"]
            elif x["decided"] == "ok_empty":
                rec["decided"] = "ok_empty"
            else:
                stats = x["stats"] if arm == "R" else None
                facts = [f"Run on this schema with no rows, the migration fails: {x['schema_error']}."] if x["schema_error"] else []
                notes = []
                if hasattr(M, "schema_cut"):
                    state, _ = M.build_state(x["catalog"], x["statements"], stats, x["tool"], x["transaction"], facts, notes=notes)
                else:
                    state, _ = M.build_state(x["catalog"], x["statements"], stats, x["tool"], x["transaction"], facts)
                rec["notes"] = notes
                if len(state) > M.MAX_CHARS:
                    rec["decided"], rec["reason"] = "cannot_foresee", "too long"
                else:
                    qs = {"lost": M.Q_LOST, "fails": M.Q_FAILS}
                    if not x["transaction"]:
                        qs["half"] = M.Q_HALF
                    rec["questions"] = qs
                    n_req += 1
                rec["state"] = state
                rec["schema_error_autocommit"] = bool(x["schema_error"])
            f.write(json.dumps(rec) + "\n")
    print(arm, "items", len(want), "need the model", n_req)
