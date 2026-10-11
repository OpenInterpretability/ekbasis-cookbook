"""Rails eval v7, the registered analysis (PREREG_v7.md section 4). Same metrics as v5/v6 (fw_eval5/analysis_v5.py, on
the migrations the product answers), with the v7 product's "fails" decision in code (ekbasis.migrations.
schema_only_plan, as _check_file applies it). Also: the reason confusion matrix (fails x loses) and how many "cannot
foresee" come from a missing external service."""
import json, os, re, sys
from collections import Counter
HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.dirname(os.path.dirname(HERE))
for d in ("fw_eval", "fw_eval5"):
    sys.path.insert(0, os.path.join(SP, d))
import analysis_v4 as V4          # noqa: E402
import analysis_v5 as V5          # noqa: E402
for m in [k for k in list(sys.modules) if k == "ekbasis" or k.startswith("ekbasis.")]:
    del sys.modules[m]
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ekbasis"))
from ekbasis import migrations as M   # noqa: E402  (the v7 product)
V4.M = V5.M = M
V4.HERE = HERE


def product(r, pred):
    if r["product"]["decided"] == "probe_fails":     # 0.1.20: a failure the code probes reproduced, decided in code
        return True, "fails"
    risky, kind = V5.product(r, pred)
    if kind in ("fails", "loses", "ok") and not r["product"]["decided"] and not r["product"].get("schema_error") and pred:
        stmts = M.split_sql((r.get("render") or {}).get("sql") or "")
        if M.schema_only_plan(stmts):
            v = M.FileVerdict(r["path"], r["framework"], r["product"]["transaction"], p_lost=pred["p_lost"], p_fail=0.0)
            return v.p_lost >= 0.5, v.kind
    return risky, kind


def main():
    rows, allr = V4.load()
    pp = os.path.join(HERE, "preds", "v7.jsonl")
    preds = {r["id"]: r for r in map(json.loads, open(pp)) if "error" not in r} if os.path.exists(pp) else {}
    print(f"items {len(allr)}, excluded {len(allr) - len(rows)}, analysed {len(rows)}; sent to the model "
          f"{sum(1 for r in rows if not r['product']['decided'])}, answered {sum(1 for r in rows if r['id'] in preds)}")
    print("exclusions:", dict(Counter(e for r in allr for e in r.get("excluded", []))))
    Vp = {r["id"]: product(r, preds.get(r["id"])) for r in rows}
    Rv = {r["id"]: V4.rules(r) for r in rows}
    ans = [r for r in rows if Vp[r["id"]][1] != "code_not_foreseen"]
    cnf = [r for r in rows if Vp[r["id"]][1] == "code_not_foreseen"]
    print(f"answered {len(ans)} (risky {sum(V4.truth(r)[0] for r in ans)}), code not foreseen {len(cnf)}")
    if preds:
        V4.verdicts(ans, Vp, Rv, "rails v7: registered P1-P4, on the migrations the product answers")
    else:
        V4.metrics(ans, Rv, "rules")
    risky = [r for r in rows if V4.truth(r)[0]]
    print(f"  reported: code not foreseen {len(cnf)}/{len(rows)} = {len(cnf) / len(rows):.3f}; truth among them "
          f"{dict(Counter(V4.truth(r)[1] for r in cnf))}")
    print(f"  reported: total recall {sum(1 for r in risky if Vp[r['id']][0])}/{len(risky)}")
    both = [r for r in ans if V4.truth(r)[0] and Vp[r["id"]][0]]
    cm = Counter((V4.truth(r)[1], Vp[r["id"]][1]) for r in both)
    print("  reported: reason matrix (truth, said):", dict(cm))
    svc = [r for r in rows if r["product"]["decided"] == "cannot_foresee_render" and
           re.search(r"redis|ECONNREFUSED|connection refused|could not connect|getaddrinfo",
                     (r.get("render") or {}).get("error") or "", re.I)]
    print(f"  reported: cannot foresee for lack of an external service: {len(svc)}; all cannot foresee "
          f"{sum(1 for r in rows if (r['product']['decided'] or '').startswith('cannot_foresee') and Vp[r['id']][1] == 'cannot_foresee')}")


if __name__ == "__main__":
    main()
