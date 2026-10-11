"""Development (not test): the schema-only fail rule on the evaluations already done (v4, v5, v6 framework items) with
the answers already obtained. For each set: verdict/reason metrics before and after, and the items it changes."""
import json, os, sys
SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SP, "fw_eval_rails7", "ekbasis"))
sys.path.insert(0, os.path.join(SP, "fw_eval"))
sys.path.insert(0, os.path.join(SP, "pr_study"))
from ekbasis import migrations as M
import analysis_v4 as V4

def run(d, predf, warn=True):
    V4.HERE = os.path.join(SP, d)
    rows, _ = V4.load()
    preds = {r["id"]: r for r in map(json.loads, open(os.path.join(SP, d, "preds", predf))) if "error" not in r}
    def verdict(r, new):
        dd = r["product"]["decided"]
        err = (r.get("render") or {}).get("error") or ""
        if warn and (dd == "cannot_foresee_code" or (dd == "cannot_foresee_render" and err.startswith(M.OFFLINE_FAIL))):
            return None
        risky, kind = V4.product(r, preds.get(r["id"]))
        if new and not dd and r["id"] in preds and not r["product"].get("schema_error"):
            stmts = M.split_sql(r["render"].get("sql") or "")
            if stmts and M.schema_only_plan(stmts):
                p = preds[r["id"]]
                pl = p["p_lost"]
                risky, kind = pl >= 0.5, ("loses" if pl >= 0.5 else "ok")
        return risky, kind
    for new in (False, True):
        V = {}
        for r in rows:
            v = verdict(r, new)
            if v is not None:
                V[r["id"]] = v
        ans = [r for r in rows if r["id"] in V]
        print(f"{d} {'NEW' if new else 'OLD'}", end="")
        V4.metrics(ans, V, "")
    changed = [r for r in rows if verdict(r, False) and verdict(r, True) != verdict(r, False)]
    print(f"  changed {len(changed)}:", [(r["path"].split("/")[-1][:40], V4.truth(r)[1], verdict(r, False)[1], "->", verdict(r, True)[1]) for r in changed][:12])

run("fw_eval_rails", "v6.jsonl")
run("fw_eval5", "v5.jsonl")
run("fw_eval", "v4.jsonl")
