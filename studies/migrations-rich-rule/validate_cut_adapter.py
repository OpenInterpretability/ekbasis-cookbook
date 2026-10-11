"""Cut-layout adapter validation without labels: from the raw facts of the v3 test and the D2 dev items (0.1.20 inputs,
probes included), render the 0.1.20 state with build_state (cut, or its named fallback), parse it back with
facts_cut, and compare the frozen rules' predictions with those on the raw facts."""
import json, os, sys, glob, collections
HERE = os.path.dirname(os.path.abspath(__file__)); SP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import facts as F, facts_cut as C, rule, rule_noseed
from ekbasis import migrations as M

# catalogs with dependency information (needed for the cut) come from corte_schema; probe facts from p2 (same ids)
def by_id(d):
    out = {}
    for p in glob.glob(os.path.join(SP, d, "*.jsonl")):
        for l in open(p):
            r = json.loads(l); out[r["id"]] = r["raw"]
    return out

for name, dc, dp in (("v3 test", "corte_schema/data/items_t2", "p2/data/items_p2"),
                     ("D2 dev", "corte_schema/data/items_d2", "p2/data/items_d2")):
    c = collections.Counter(); diffs = []
    RC, RP = by_id(dc), by_id(dp)
    for i, rc in RC.items():
        if i not in RP or "relations" not in (rc.get("catalog") or {}):
            continue
        raw = dict(rc); raw["probe_R"] = RP[i].get("probe_R"); raw["probe_N"] = RP[i].get("probe_N")
        if raw.get("decided"):
            continue
        if True:
            for reg in "RN":
                f_raw = F.view(raw, reg)
                if f_raw.probe_decided:
                    continue
                stats = raw["stats"] if reg == "R" else None
                facts = ([f"Run on this schema with no rows, the migration fails: {raw['schema_error']}."]
                         if raw["schema_error"] else []) + list(f_raw.probe_facts)
                st, _ = M.build_state(raw["catalog"], raw["statements"], stats, raw["tool"], raw["transaction"], facts)
                c[reg, "cut" if "migration touches" in st else "named"] += 1
                try:
                    f_par = C.from_state(st, raw["statements"], raw["transaction"], raw["schema_error"], raw["tool"])
                except C.Unconvertible as e:
                    c[reg, "unconvertible"] += 1; diffs.append((i, reg, "unconv", str(e)[:90])); continue
                c[reg, "probe facts equal" if f_par.probe_facts == f_raw.probe_facts else "probe facts differ"] += 1
                for mod in (rule, rule_noseed):
                    a = mod.decide(f_raw)[0]; b = mod.decide(f_par)[0]
                    c[reg, mod.__name__, "agree" if a == b else "differ"] += 1
                    if a != b:
                        diffs.append((i, reg, mod.__name__, a, b))
    print(name, dict(sorted(c.items(), key=str)))
    for x in diffs[:12]:
        print("  ", x)
