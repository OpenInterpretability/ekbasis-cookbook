"""Eval v2, step 4: the registered analysis (PREREG_v2.md section 5). Reads preds/a2.jsonl, preds/a1.jsonl, the study's
v1 answers and data/labels_v2.jsonl. Metric functions come unchanged from the study's frozen analysis.py."""
import json
import math
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.join(os.path.dirname(HERE), "pr_study")
sys.path.insert(0, STUDY)
import analysis as A   # noqa: E402
import rules as RU     # noqa: E402

THR = 0.5


def load(path):
    return {r["id"]: r for r in map(json.loads, open(path)) if "error" not in r}


def binom_two_sided(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def timing(P):
    def t(p, k):
        m = re.search(k + r';(?:desc="[^"]*";)?dur=([\d.]+)', p.get("server_timing") or "")
        return float(m.group(1)) if m else None
    q = [t(p, "queue") for p in P.values() if t(p, "queue") is not None]
    m = [t(p, "model") for p in P.values() if t(p, "model") is not None]
    tok = [p["usage"]["input_tokens"] for p in P.values() if p.get("usage")]
    return (f"model median {st.median(m) / 1000:.2f} s, queue median {st.median(q) / 1000:.2f} s, "
            f"input tokens {sum(tok):,} (median {st.median(tok):.0f})") if m and tok else "n/a"


def main():
    labels = {r["id"]: r for r in map(json.loads, open(os.path.join(HERE, "data", "labels_v2.jsonl")))}
    study = {it["id"]: it for it in A.load_items(True)}
    v1 = A.load_preds("ekbasis")
    arms = {"v1": v1}
    for arm in ("a2", "a1"):
        p = os.path.join(HERE, "preds", f"{arm}.jsonl")
        if os.path.exists(p):
            arms[arm] = load(p)
    ids = sorted(k for k in labels if all(k in P for P in arms.values()))
    print(f"items with every arm answered: {len(ids)} of {len(labels)}; arms: {list(arms)}")
    for arm, P in arms.items():
        if arm != "v1":
            print(f"  {arm}: {timing(P)}")
    lab = lambda k: labels[k]["label_product"]
    Aids = [k for k in ids if labels[k]["stratum"] == "A"]
    yA = [lab(k)["lost"] for k in Aids]
    yF = [lab(k)["fails"] for k in ids]
    r3 = [float(RU.r3(study[k]["statements"])) for k in Aids]
    f1r = [float(RU.f1(study[k]["statements"])) for k in ids]

    def summary(arm):
        P = arms[arm]
        sA = [P[k]["p_lost"] for k in Aids]
        sF = [P[k]["p_fails"] for k in ids]
        pl, rl, fl = A.prf(yA, [x >= THR for x in sA])
        pf, rf, ff = A.prf(yF, [x >= THR for x in sF])
        print(f"{arm:3s} lost(A): AUROC {A.auroc(yA, sA):.3f}  P {pl:.3f} R {rl:.3f} F1 {fl:.3f}  ECE {A.ece(yA, sA):.3f} | "
              f"fails(all): AUROC {A.auroc(yF, sF):.3f}  P {pf:.3f} R {rf:.3f} F1 {ff:.3f}  ECE {A.ece(yF, sF):.3f}")
        return sA, sF

    print(f"\nlabels (product regime, this run): stratum A n={len(Aids)} lost={sum(yA)}; all n={len(ids)} fails={sum(yF)}")
    S = {arm: summary(arm) for arm in arms}
    pr = A.prf(yA, [x >= THR for x in r3])
    print(f"R3  lost(A): P {pr[0]:.3f} R {pr[1]:.3f} F1 {pr[2]:.3f}; rule F1 fails(all): F1 {A.prf(yF, [x >= THR for x in f1r])[2]:.3f}")
    if "a2" not in arms:
        return
    sA2, sF2 = S["a2"]
    sA1v, _ = S["v1"]
    print("\n== Registered hypotheses (PREREG_v2 section 5)")
    # H1: loss false alarms on migrations that fail (and lose nothing) under the product's regime
    fl = [i for i, k in enumerate(Aids) if lab(k)["fails"] and not lab(k)["lost"]]
    fp2 = [sA2[i] >= THR for i in fl]
    fp1 = [sA1v[i] >= THR for i in fl]
    b = sum(1 for x, y in zip(fp1, fp2) if x and not y)
    c = sum(1 for x, y in zip(fp1, fp2) if y and not x)
    p = binom_two_sided(b, c)
    r2, r1 = sum(fp2) / len(fl), sum(fp1) / len(fl)
    print(f"H1 loss false alarms on failing migrations (A, n={len(fl)}): v1 {sum(fp1)} ({r1:.2f}) -> a2 {sum(fp2)} ({r2:.2f}); "
          f"McNemar exact p={p:.4f} -> {'PASS' if r2 <= 0.40 and r2 < r1 and p < 0.05 else 'FAIL'}")
    a = A.auroc(yA, sA2)
    ci = A.boot(lambda idx: A.auroc([yA[i] for i in idx], [sA2[i] for i in idx]), len(Aids))
    print(f"H2 lost AUROC (A) {a:.3f} [{ci[0]:.3f},{ci[1]:.3f}] -> {'PASS' if a >= 0.90 and ci[0] >= 0.85 else 'FAIL'}")
    d = lambda idx: (A.prf([yA[i] for i in idx], [sA2[i] >= THR for i in idx])[2] -
                     A.prf([yA[i] for i in idx], [r3[i] >= THR for i in idx])[2])
    c3 = A.boot(d, len(Aids))
    print(f"H3 F1(a2) - F1(R3), lost (A): {d(range(len(Aids))):+.3f} [{c3[0]:+.3f},{c3[1]:+.3f}] -> {'PASS' if c3[0] > 0 else 'FAIL'}")
    af = A.auroc(yF, sF2)
    cf = A.boot(lambda idx: A.auroc([yF[i] for i in idx], [sF2[i] for i in idx]), len(ids))
    d4 = lambda idx: (A.prf([yF[i] for i in idx], [sF2[i] >= THR for i in idx])[2] -
                      A.prf([yF[i] for i in idx], [f1r[i] >= THR for i in idx])[2])
    c4 = A.boot(d4, len(ids))
    print(f"H4 fails AUROC (all) {af:.3f} [{cf[0]:.3f},{cf[1]:.3f}]; F1(a2) - F1(rule) {d4(range(len(ids))):+.3f} "
          f"[{c4[0]:+.3f},{c4[1]:+.3f}] -> {'PASS' if af >= 0.90 and cf[0] >= 0.85 and c4[0] > 0 else 'FAIL'}")
    e = A.ece(yA, sA2)
    print(f"H5 ECE lost (A) {e:.3f} -> {'PASS' if e <= 0.10 else 'FAIL'}")
    d6 = lambda idx: A.auroc([yA[i] for i in idx], [sA2[i] for i in idx]) - A.auroc([yA[i] for i in idx], [sA1v[i] for i in idx])
    c6 = A.boot(d6, len(Aids))
    print(f"H6 AUROC(a2) - AUROC(v1), lost (A): {d6(range(len(Aids))):+.3f} [{c6[0]:+.3f},{c6[1]:+.3f}] -> "
          f"{'PASS' if c6[0] > -0.03 else 'FAIL'}")

    print("\n== Exploratory")
    for arm in arms:
        P = arms[arm]
        for reg in (True, False):
            sub = [i for i, k in enumerate(Aids) if labels[k]["transaction"] == reg]
            if sub and 0 < sum(yA[i] for i in sub) < len(sub):
                print(f"{arm} lost AUROC (A, {'transaction' if reg else 'autocommit'} files, n={len(sub)}): "
                      f"{A.auroc([yA[i] for i in sub], [P[Aids[i]]['p_lost'] for i in sub]):.3f}")
    for arm in arms:
        P = arms[arm]
        fpc = sum(P[Aids[i]]["p_lost"] >= THR for i in fl)
        okn = [i for i, k in enumerate(Aids) if not lab(k)["fails"]]
        print(f"{arm}: loss false alarms on failing / on clean migrations (A): {fpc}/{len(fl)} / "
              f"{sum(P[Aids[i]]['p_lost'] >= THR and not yA[i] for i in okn)}/{sum(not yA[i] for i in okn)}")
    # the v1 arm against the labels of its own run (study), for reference
    yo = [study[k]["label_tx"]["lost"] if labels[k]["transaction"] else study[k]["label"]["lost"] for k in Aids]
    print(f"v1 lost AUROC (A) against the study run's labels in the product regime: {A.auroc(yo, sA1v):.3f}")


if __name__ == "__main__":
    main()
