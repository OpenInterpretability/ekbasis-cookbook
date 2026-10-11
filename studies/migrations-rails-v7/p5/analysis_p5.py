"""P5 (v7): non-inferiority of the v7 "fails" decision on the v3 sample (184 SQL migrations). OLD = the main branch's
verdict (main 4654485, 0.1.20 + intent threshold, loaded from oldpkg/ekbasis_old), NEW = the v7 branch's; the states are identical (the decision applies after the answer), so
one set of answers obtained now on the current server serves both. Criteria (PREREG_v7 section 5): accuracy NEW >= OLD
- 0.02; false alarms NEW <= OLD + 3 items; recall NEW >= OLD - 2 items; reason exact NEW >= OLD - 2 items."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(SP, "pr_eval3"))
import analysis_v3 as V3                  # noqa: E402  (product_verdict, rule_verdict, truth, kind_ok)
for m in [k for k in list(sys.modules) if k == "ekbasis" or k.startswith("ekbasis.")]:
    del sys.modules[m]
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ekbasis"))
from ekbasis import migrations as M       # noqa: E402  NEW
sys.path.insert(0, os.path.join(HERE, "oldpkg"))
from ekbasis_old import migrations as MO  # noqa: E402  OLD
V3.M = MO
from frame import R                       # noqa: E402
from sqlsplit import split_sql            # noqa: E402


def main():
    labs = {r["id"]: r for r in map(json.loads, open(os.path.join(HERE, "data", "labels_v3.jsonl")))}
    pp = os.path.join(HERE, "preds", "p5.jsonl")
    preds = {r["id"]: r for r in map(json.loads, open(pp)) if "error" not in r} if os.path.exists(pp) else {}
    apart = sorted(k for k in labs if not labs[k].get("state_same", True))
    print(f"A1: items whose OLD and NEW states differ (out of the analysis, counted apart): {len(apart)}", apart)
    ids = sorted(k for k in labs if k not in apart)
    print(f"items {len(ids)}, answered {sum(1 for k in ids if k in preds)}")
    if not preds:
        return
    stm = {k: M.split_sql(open(os.path.join(R, labs[k]["repo"], labs[k]["path"]), encoding="utf-8",
                                errors="replace").read()) for k in ids}
    def with_module(mod, k):
        if labs[k]["decided"] == "probe_fails":      # 0.1.20: decided in code by the code probes (OLD and NEW alike)
            return True, "fails"
        V3.M = mod                       # analysis_v3.product_verdict builds the FileVerdict of this version
        return V3.product_verdict(labs[k], preds[k]) if (labs[k]["decided"] or k in preds) else (True, "cannot_foresee")
    def old(k):
        return with_module(MO, k)
    def new(k):
        risky, kind = with_module(M, k)
        l = labs[k]
        if not l["decided"] and not l["schema_error"] and k in preds and M.schema_only_plan(stm[k]):
            v = M.FileVerdict(l["path"], l["tool"], l["transaction"], p_lost=preds[k]["p_lost"], p_fail=0.0)
            return v.p_lost >= 0.5, v.kind
        return risky, kind
    res = {}
    for name, f in (("OLD", old), ("NEW", new)):
        V = {k: f(k) for k in ids}
        tr = {k: V3.truth(labs[k]) for k in ids}
        acc = sum(V[k][0] == tr[k][0] for k in ids) / len(ids)
        risky = [k for k in ids if tr[k][0]]
        caught = [k for k in risky if V[k][0]]
        reason = sum(V3.kind_ok(V[k][1], tr[k][1]) for k in caught)
        fa = sum(V[k][0] for k in ids if not tr[k][0])
        res[name] = (acc, fa, len(caught), reason)
        print(f"{name}: accuracy {acc:.3f}, false alarms {fa}/{sum(1 for k in ids if not tr[k][0])}, recall "
              f"{len(caught)}/{len(risky)}, reason exact {reason}/{len(caught)}")
        if name == "NEW":
            ch = [k for k in ids if old(k) != new(k)]
            print(f"changed by the decision: {len(ch)}", [(k.split('/')[-1][:40], tr[k][1], old(k)[1], '->', new(k)[1]) for k in ch])
    (ao, fo, ro, so), (an, fn, rn, sn) = res["OLD"], res["NEW"]
    ok = an >= ao - 0.02 and fn <= fo + 3 and rn >= ro - 2 and sn >= so - 2
    print(f"P5 accuracy {an:.3f} >= {ao - 0.02:.3f}; false alarms {fn} <= {fo + 3}; recall {rn} >= {ro - 2}; reason "
          f"{sn} >= {so - 2} -> {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()
