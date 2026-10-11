"""Adapter validation without labels (v3 test raws and D2 dev raws): render the 0.1.17 named state from the raw facts,
parse it back with facts_v5, and compare (1) the parsed tables/columns with the catalog and (2) the frozen rules'
predictions on parsed facts vs on the raw facts."""
import json, os, sys, glob, collections
HERE = os.path.dirname(os.path.abspath(__file__)); SP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import facts as F, facts_v5 as A, rule, rule_noseed
from ekbasis import migrations as M

def raws(d):
    out = {}
    for p in glob.glob(os.path.join(SP, d, "*.jsonl")):
        for l in open(p):
            r = json.loads(l); out[r["id"]] = r["raw"]
    return out

for name, d in (("v3 test", "p2/data/items_p2"), ("D2 dev", "p2/data/items_d2")):
    R = raws(d)
    c = collections.Counter(); bad = []
    for i, raw in R.items():
        if raw.get("decided"):
            continue
        for reg in "RN":
            f_raw = F.view(raw, reg)
            stats = raw["stats"] if reg == "R" else None
            facts = [f"Run on this schema with no rows, the migration fails: {raw['schema_error']}."] if raw["schema_error"] else []
            st, shown = M._named_state(raw["catalog"], raw["statements"], stats, raw["tool"], raw["transaction"], facts)
            try:
                cat, sts, _ = A.parse_state(st)
            except A.Unconvertible as e:
                c[reg, "unconvertible"] += 1; bad.append((i, str(e))); continue
            # fidelity of columns
            byn = {t["name"]: t for t in raw["catalog"]["tables"]}
            ok = all(t["name"] in byn and [(x["name"], x["type"], x["notnull"]) for x in t["cols"]] ==
                     [(x["name"], x["type"], x["notnull"]) for x in byn[t["name"]]["cols"] or []] for t in cat["tables"])
            c[reg, "cols_equal" if ok else "cols_differ"] += 1
            f_par = F.Facts(tool=raw["tool"], transaction=bool(raw["transaction"]), stmts=f_raw.stmts, flat=f_raw.flat,
                            schema_error=raw["schema_error"], catalog=cat, regime=reg, stats=sts, probe_facts=[],
                            probe_decided=None)
            for mod in (rule, rule_noseed):
                a = mod.decide(f_raw)[0]; b = mod.decide(f_par)[0]
                c[reg, mod.__name__, "agree" if a == b else "differ"] += 1
    print(name, dict(sorted(c.items(), key=str)))
    for b in bad[:5]: print("  ", b)
