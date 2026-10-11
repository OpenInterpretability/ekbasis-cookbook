"""Eval v3, step 4: the registered analysis (PREREG_v3.md section 4). The product's verdict and reason are computed with
the product's own code (ekbasis.migrations.FileVerdict at the registered commit) from the model's answers and the
decisions made in code; the rules baseline is R3 OR the failure rule F1 (study's rules.py), reason F1 -> fails."""
import json
import math
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.join(os.path.dirname(HERE), "pr_study")
sys.path.insert(0, STUDY)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "migguard_ekbasis"))
import analysis as A            # noqa: E402  (frozen metric functions: boot)
import rules as RU              # noqa: E402
from ekbasis import migrations as M   # noqa: E402

T_LOST = T_FAIL = 0.5


def binom_two_sided(b, c):
    n, k = b + c, min(b, c)
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def product_verdict(lab, pred):
    """(risky, kind) as migrate-check decides them."""
    d = lab["decided"]
    if d and d.startswith("cannot_foresee"):
        return True, "cannot_foresee"
    if d == "schema":
        return True, "schema"
    if d == "ok_empty":
        return False, "ok"
    v = M.FileVerdict(lab["path"], lab["tool"], lab["transaction"], p_lost=pred["p_lost"], p_fail=pred["p_fails"],
                      lost_threshold=T_LOST, fail_threshold=T_FAIL)
    if lab["schema_error"]:                 # autocommit file that fails on the schema: p_fail = 1, as _check_file does
        v.schema_error, v.p_fail = lab["schema_error"], 1.0
    risky = bool(v.schema_error) or v.p_lost >= T_LOST or v.p_fail >= T_FAIL
    return risky, v.kind


def rule_verdict(stmts):
    f, l = RU.f1(stmts), RU.r3(stmts)
    return f or l, ("fails" if f else "loses" if l else "ok")


def truth(lab):
    lp = lab["label_product"]
    return lp["fails"] or lp["lost"], ("fails" if lp["fails"] else "loses" if lp["lost"] else "ok")


def kind_ok(pred_kind, true_kind):
    return {"fails": "fails", "schema": "fails", "loses": "loses"}.get(pred_kind) == true_kind


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def main():
    labs = {r["id"]: r for r in map(json.loads, open(os.path.join(HERE, "data", "labels_v3.jsonl")))}
    preds = {}
    p = os.path.join(HERE, "preds", "v3.jsonl")
    if os.path.exists(p):
        preds = {r["id"]: r for r in map(json.loads, open(p)) if "error" not in r}
    stmts = {}
    from frame import R
    from sqlsplit import split_sql
    for k, lab in labs.items():
        stmts[k] = split_sql(open(os.path.join(R, lab["repo"], lab["path"]), encoding="utf-8", errors="replace").read())
    need = [k for k in labs if not labs[k]["decided"]]
    missing = [k for k in need if k not in preds]
    print(f"items {len(labs)}; sent to the model {len(need)}; answered {len(need) - len(missing)}; decided in code "
          f"{len(labs) - len(need)}")
    if missing:
        print(f"{len(missing)} without an answer: counted as cannot foresee (risky, wrong reason)")
    ids = sorted(labs)
    tr = {k: truth(labs[k]) for k in ids}
    pv = {k: (product_verdict(labs[k], preds[k]) if (labs[k]["decided"] or k in preds) else (True, "cannot_foresee"))
          for k in ids}
    rv = {k: rule_verdict(stmts[k]) for k in ids}
    risky_true = [k for k in ids if tr[k][0]]
    benign = [k for k in ids if not tr[k][0]]
    print(f"truth: risky {len(risky_true)} (fails {sum(tr[k][1] == 'fails' for k in ids)}, loses only "
          f"{sum(tr[k][1] == 'loses' for k in ids)}), benign {len(benign)}")

    def metrics(V, name):
        acc = sum(V[k][0] == tr[k][0] for k in ids) / len(ids)
        both = [k for k in risky_true if V[k][0]]
        rex = sum(kind_ok(V[k][1], tr[k][1]) for k in both) / len(both) if both else float("nan")
        fa = sum(V[k][0] for k in benign) / len(benign)
        rec = len(both) / len(risky_true)
        print(f"{name:<10} accuracy {acc:.3f}  recall {rec:.3f} ({len(both)}/{len(risky_true)})  reason exact {rex:.3f} "
              f"(n={len(both)})  false alarms on benign {fa:.3f} ({sum(V[k][0] for k in benign)}/{len(benign)})")
        return acc, rex, fa, rec, both

    print()
    accR, rexR, faR, recR, _ = metrics(rv, "rules")
    if not preds:
        return
    acc, rex, fa, rec, both = metrics(pv, "product")
    print("\n== Registered (PREREG_v3 section 4)")
    ci = A.boot(lambda idx: sum(pv[ids[i]][0] == tr[ids[i]][0] for i in idx) / len(idx), len(ids))
    d = lambda idx: (sum(pv[ids[i]][0] == tr[ids[i]][0] for i in idx) - sum(rv[ids[i]][0] == tr[ids[i]][0] for i in idx)) / len(idx)
    cd = A.boot(d, len(ids))
    print(f"P1 verdict accuracy {acc:.3f} [{ci[0]:.3f},{ci[1]:.3f}]; minus rules {d(range(len(ids))):+.3f} "
          f"[{cd[0]:+.3f},{cd[1]:+.3f}] -> {'PASS' if acc >= 0.85 and ci[0] >= 0.80 and cd[0] > 0 else 'FAIL'}")
    k_ok = sum(kind_ok(pv[k][1], tr[k][1]) for k in both)
    w = wilson(k_ok, len(both))
    print(f"P2 reason exact on true-risky flagged items {k_ok}/{len(both)} = {rex:.3f} [{w[0]:.3f},{w[1]:.3f}] -> "
          f"{'PASS' if rex >= 0.85 and w[0] >= 0.75 else 'FAIL'}")
    nfa = sum(pv[k][0] for k in benign)
    wf = wilson(nfa, len(benign))
    b = sum(1 for k in benign if rv[k][0] and not pv[k][0])
    c = sum(1 for k in benign if pv[k][0] and not rv[k][0])
    pm = binom_two_sided(b, c)
    print(f"P3 false alarms on benign {nfa}/{len(benign)} = {fa:.3f} [{wf[0]:.3f},{wf[1]:.3f}]; rules {faR:.3f}; McNemar "
          f"p={pm:.4f} -> {'PASS' if fa <= 0.20 and wf[1] <= 0.30 and fa < faR and pm < 0.05 else 'FAIL'}")
    wr = wilson(len(both), len(risky_true))
    print(f"P4 recall {rec:.3f} [{wr[0]:.3f},{wr[1]:.3f}] -> {'PASS' if rec >= 0.85 else 'FAIL'}")

    print("\n== Exploratory")
    for s_ in "ABC":
        sub = [k for k in ids if labs[k]["stratum"] == s_]
        print(f"stratum {s_}: n={len(sub)} truth risky {sum(tr[k][0] for k in sub)}; product accuracy "
              f"{sum(pv[k][0] == tr[k][0] for k in sub) / len(sub):.3f}; rules {sum(rv[k][0] == tr[k][0] for k in sub) / len(sub):.3f}")
    fl = [k for k in both if tr[k][1] == "fails"]
    print(f"reason on failing migrations flagged: 'fails' {sum(pv[k][1] in ('fails', 'schema') for k in fl)}/{len(fl)}")
    lo = [k for k in both if tr[k][1] == "loses"]
    print(f"reason on loss-only migrations flagged: 'loses' {sum(pv[k][1] == 'loses' for k in lo)}/{len(lo)}")
    old = lambda k: ("loses" if preds[k]["p_lost"] >= T_LOST else "fails") if k in preds else pv[k][1]
    print(f"v2 reason order (loss first) would be exact on {sum(kind_ok(old(k), tr[k][1]) for k in both)}/{len(both)}")

    def tm(P_, key):
        out = []
        for r in P_.values():
            m = re.search(key + r';(?:desc="[^"]*";)?dur=([\d.]+)', r.get("server_timing") or "")
            if m:
                out.append(float(m.group(1)) / 1000)
        return out
    tok = [r["usage"]["input_tokens"] for r in preds.values() if r.get("usage")]
    if tok:
        print(f"cost: {sum(tok):,} input tokens (median {st.median(tok):.0f}); model median {st.median(tm(preds, 'model')):.2f} s; "
              f"queue median {st.median(tm(preds, 'queue')):.2f} s")


if __name__ == "__main__":
    main()
