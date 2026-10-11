"""Framework items (v5 Django/Alembic, v6 Rails) for the held-out comparison. No label is read here."""
import json, os, sys, glob
HERE = os.path.dirname(os.path.abspath(__file__)); SP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import facts_v5 as A

EVALS = {"v5": ("fw_eval5", "requests_v5.jsonl", "v5.jsonl"), "v6": ("fw_eval_rails", "requests_v6.jsonl", "v6.jsonl")}
DROP = ("label", "lost_detail", "run_error", "seeded_rows")


def items(ev):
    d, req, _ = EVALS[ev]
    out = []
    for p in sorted(glob.glob(os.path.join(SP, d, "data", "items", "*.jsonl"))):
        for l in open(p):
            r = json.loads(l)
            r = {k: v for k, v in r.items() if k not in DROP}
            r["id"] = f"{r['project']}/{r['path']}"
            if not r.get("excluded"):
                out.append(r)
    states = {}
    for l in open(os.path.join(SP, d, "data", req)):
        q = json.loads(l)
        states[q["id"]] = q["state"]
    return out, states


def facts_for(r, states):
    """Facts for an item sent to the model, or raises A.Unconvertible."""
    st = states.get(r["id"]) or (r["product"].get("state"))
    if not st:
        raise A.Unconvertible("no state")
    return A.from_state(st, (r.get("render") or {}).get("sql") or "", r["product"]["transaction"],
                        r["product"].get("schema_error"), tool=r["framework"])
