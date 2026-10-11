"""Recomputes the follow-up evaluation (PREREG_v2) from the released answers: ../answers.jsonl (the study's v1 answers
and rule outputs) and answers_v2.jsonl (A2 = the product's state, A1 = the ablation, labels of the re-execution).

    python recompute_v2.py      # standard library only; writes recompute_v2_output.txt
"""
import io
import json
import math
import os
import sys
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "frozen"))
import analysis as A  # noqa: E402  (the study's frozen metric functions)

THR = 0.5


def binom_two_sided(b, c):
    n, k = b + c, min(b, c)
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def main():
    v1 = {r["id"]: r for r in map(json.loads, open(os.path.join(os.path.dirname(HERE), "answers.jsonl")))}
    v2 = {r["id"]: r for r in map(json.loads, open(os.path.join(HERE, "answers_v2.jsonl")))}
    ids = sorted(v2)
    Aids = [k for k in ids if v2[k]["stratum"] == "A"]
    lab = lambda k: v2[k]["label_product"]
    yA = [lab(k)["lost"] for k in Aids]
    yF = [lab(k)["fails"] for k in ids]
    s = {"v1": ([v1[k]["ekbasis"]["lost"] for k in Aids], [v1[k]["ekbasis"]["fails"] for k in ids])}
    for arm in ("a2", "a1"):
        s[arm] = ([v2[k][arm]["lost"] for k in Aids], [v2[k][arm]["fails"] for k in ids])
    r3 = [float(v1[k]["rules"]["R3"]) for k in Aids]
    rf = [float(v1[k]["rules"]["F1"]) for k in ids]
    print(f"stratum A n={len(Aids)} lost={sum(yA)}; all n={len(ids)} fails={sum(yF)}")
    for arm, (sa, sf) in s.items():
        pl = A.prf(yA, [x >= THR for x in sa])
        pf = A.prf(yF, [x >= THR for x in sf])
        print(f"{arm}: lost(A) AUROC {A.auroc(yA, sa):.3f} P {pl[0]:.3f} R {pl[1]:.3f} F1 {pl[2]:.3f} ECE {A.ece(yA, sa):.3f} | "
              f"fails AUROC {A.auroc(yF, sf):.3f} P {pf[0]:.3f} R {pf[1]:.3f} F1 {pf[2]:.3f}")
    print(f"R3 lost(A) F1 {A.prf(yA, [x >= THR for x in r3])[2]:.3f}; failure rule F1 {A.prf(yF, [x >= THR for x in rf])[2]:.3f}")
    sa2, sf2 = s["a2"]
    sa1 = s["v1"][0]
    fl = [i for i, k in enumerate(Aids) if lab(k)["fails"] and not lab(k)["lost"]]
    f1_, f2_ = [sa1[i] >= THR for i in fl], [sa2[i] >= THR for i in fl]
    b = sum(x and not y for x, y in zip(f1_, f2_))
    c = sum(y and not x for x, y in zip(f1_, f2_))
    r2 = sum(f2_) / len(fl)
    print(f"H1 false alarms on failing migrations (A, n={len(fl)}): v1 {sum(f1_)} -> a2 {sum(f2_)}; McNemar p="
          f"{binom_two_sided(b, c):.4f} -> {'PASS' if r2 <= 0.40 and sum(f2_) < sum(f1_) and binom_two_sided(b, c) < 0.05 else 'FAIL'}")
    a = A.auroc(yA, sa2)
    ci = A.boot(lambda idx: A.auroc([yA[i] for i in idx], [sa2[i] for i in idx]), len(Aids))
    print(f"H2 lost AUROC {a:.3f} [{ci[0]:.3f},{ci[1]:.3f}] -> {'PASS' if a >= 0.90 and ci[0] >= 0.85 else 'FAIL'}")
    d = lambda idx: A.prf([yA[i] for i in idx], [sa2[i] >= THR for i in idx])[2] - A.prf([yA[i] for i in idx], [r3[i] >= THR for i in idx])[2]
    c3 = A.boot(d, len(Aids))
    print(f"H3 F1(a2) - F1(R3) {d(range(len(Aids))):+.3f} [{c3[0]:+.3f},{c3[1]:+.3f}] -> {'PASS' if c3[0] > 0 else 'FAIL'}")
    af = A.auroc(yF, sf2)
    cf = A.boot(lambda idx: A.auroc([yF[i] for i in idx], [sf2[i] for i in idx]), len(ids))
    d4 = lambda idx: A.prf([yF[i] for i in idx], [sf2[i] >= THR for i in idx])[2] - A.prf([yF[i] for i in idx], [rf[i] >= THR for i in idx])[2]
    c4 = A.boot(d4, len(ids))
    print(f"H4 fails AUROC {af:.3f} [{cf[0]:.3f},{cf[1]:.3f}], F1 - rule {d4(range(len(ids))):+.3f} [{c4[0]:+.3f},{c4[1]:+.3f}] -> "
          f"{'PASS' if af >= 0.90 and cf[0] >= 0.85 and c4[0] > 0 else 'FAIL'}")
    print(f"H5 ECE lost(A) {A.ece(yA, sa2):.3f} -> {'PASS' if A.ece(yA, sa2) <= 0.10 else 'FAIL'}")
    d6 = lambda idx: A.auroc([yA[i] for i in idx], [sa2[i] for i in idx]) - A.auroc([yA[i] for i in idx], [sa1[i] for i in idx])
    c6 = A.boot(d6, len(Aids))
    print(f"H6 AUROC(a2) - AUROC(v1) {d6(range(len(Aids))):+.3f} [{c6[0]:+.3f},{c6[1]:+.3f}] -> {'PASS' if c6[0] > -0.03 else 'FAIL'}")


if __name__ == "__main__":
    buf = io.StringIO()
    with redirect_stdout(buf):
        main()
    print(buf.getvalue())
    open(os.path.join(HERE, "recompute_v2_output.txt"), "w").write(buf.getvalue())
