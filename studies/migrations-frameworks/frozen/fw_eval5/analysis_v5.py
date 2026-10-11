"""Framework eval v5, the registered analysis (PREREG_v5.md section 4). The product runs with on-code=warn: a migration
with code that is not SQL (RunPython, no offline SQL) is "code_not_foreseen" - listed for review by hand, not
blocking. P1-P4 are computed on the migrations the product answers (all but code_not_foreseen); the code_not_foreseen
share and the total recall (counting them as not caught) are reported without a pass criterion."""
import glob
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "fw_eval"))
import analysis_v4 as V4                 # noqa: E402  (frozen v4: metrics, rules, verdict from the product's code)
from ekbasis import migrations as M      # noqa: E402

V4.HERE = HERE


def product(r, pred):
    d = r["product"]["decided"]
    err = (r.get("render") or {}).get("error") or ""
    if d == "cannot_foresee_code" or (d == "cannot_foresee_render" and err.startswith(M.OFFLINE_FAIL)):
        return False, "code_not_foreseen"
    return V4.product(r, pred)


def main():
    rows, allr = V4.load()
    pp = os.path.join(HERE, "preds", "v5.jsonl")
    preds = {r["id"]: r for r in map(json.loads, open(pp)) if "error" not in r} if os.path.exists(pp) else {}
    from collections import Counter
    print(f"items {len(allr)}, excluded {len(allr) - len(rows)}, analysed {len(rows)}; sent to the model "
          f"{sum(1 for r in rows if not r['product']['decided'])}, answered {sum(1 for r in rows if r['id'] in preds)}")
    print("exclusions:", dict(Counter(e for r in allr for e in r.get("excluded", []))))
    Vp = {r["id"]: product(r, preds.get(r["id"])) for r in rows}
    Rv = {r["id"]: V4.rules(r) for r in rows}
    for fw in ("django", "alembic"):
        sub = [r for r in rows if r["framework"] == fw]
        ans = [r for r in sub if Vp[r["id"]][1] != "code_not_foreseen"]
        cnf = [r for r in sub if Vp[r["id"]][1] == "code_not_foreseen"]
        print(f"\n######## {fw}: {len(sub)} migrations, answered {len(ans)}, code not foreseen {len(cnf)}")
        if preds:
            V4.verdicts(ans, Vp, Rv, f"{fw}: registered P1-P4, on the migrations the product answers")
        else:
            V4.metrics(ans, Rv, "rules")
        risky = [r for r in sub if V4.truth(r)[0]]
        caught = [r for r in risky if Vp[r["id"]][0]]
        print(f"  reported: code not foreseen {len(cnf)}/{len(sub)} = {len(cnf) / len(sub):.3f}; truth among them "
              f"{dict(Counter(V4.truth(r)[1] for r in cnf))}")
        print(f"  reported: total recall (code not foreseen counted as not caught) {len(caught)}/{len(risky)} = "
              f"{len(caught) / len(risky):.3f}" if risky else "  no risky migrations")
    tok = [p["usage"]["input_tokens"] for p in preds.values() if p.get("usage")]
    mt = [float(m.group(1)) for p in preds.values() for m in [re.search(r'model;(?:desc="[^"]*";)?dur=([\d.]+)',
                                                                        p.get("server_timing") or "")] if m]
    if tok:
        print(f"\ncost: {sum(tok):,} input tokens; model median {st.median(mt) / 1000:.2f} s")


if __name__ == "__main__":
    main()
