"""Rails v7 (A1) and P5 items for the 0.1.21 retest. No label is read here."""
import json, os, sys, glob
HERE = os.path.dirname(os.path.abspath(__file__)); SP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import facts_cut as C
from ekbasis import migrations as M
R7 = os.path.join(SP, "fw_eval_rails7")
DROP = ("label", "label_tx", "label_auto", "label_product", "lost_detail", "run_error", "seeded_rows", "empty_errors")


def v7_items():
    out = []
    for p in sorted(glob.glob(os.path.join(R7, "eval", "data", "items", "*.jsonl"))):
        for l in open(p):
            r = {k: v for k, v in json.loads(l).items() if k not in DROP}
            r["id"] = f"{r['project']}/{r['path']}"
            if not r.get("excluded"):
                out.append(r)
    states = {q["id"]: q["state"] for q in map(json.loads, open(os.path.join(R7, "eval", "data", "requests_v7.jsonl")))}
    return out, states


def v7_facts(r, states):
    st = states.get(r["id"])
    if not st:
        raise C.Unconvertible("no state")
    stmts = M.split_sql((r.get("render") or {}).get("sql") or "")
    return C.from_state(st, stmts, r["product"]["transaction"], r["product"].get("schema_error"), tool="rails")


def p5_items():
    out = []
    for p in sorted(glob.glob(os.path.join(R7, "p5", "data", "items", "*.jsonl"))):
        for l in open(p):
            r = {k: v for k, v in json.loads(l).items() if k not in DROP}
            out.append(r)
    return out


def p5_facts(r, raw_stmts):
    pr = r["product"]
    st = pr.get("state")
    if not st:
        raise C.Unconvertible("no state")
    return C.from_state(st, raw_stmts, pr["transaction"], pr.get("schema_error"), tool=pr.get("tool") or "generic")
