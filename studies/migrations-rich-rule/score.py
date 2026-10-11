"""T2 scoring (PREREG §4, §6, §7). python3 score.py > results.txt"""
import json, os, random, sys
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SP, "p2"))
from score_v4 import verdict  # noqa: E402


def load(p):
    return {json.loads(l)["id"]: json.loads(l) for l in open(p)}


L = load(os.path.join(SP, "v4/data/labels_v3.jsonl"))


def truth(i):
    lp = L[i]["label_product"]
    risky = bool(lp["lost"] or lp["fails"])
    return risky, ("fails" if lp["fails"] else ("loses" if risky else None))


def ekb(reg, sens=False):
    SO, SN = load(f"{SP}/p2/st/t2_old.{reg}.jsonl"), load(f"{SP}/p2/st/t2_new.{reg}.jsonl")
    AO, AN = load(f"{SP}/p2/ans/t2_old.{reg}.jsonl"), load(f"{SP}/p2/ans/t2_new.{reg}.jsonl")
    if sens:
        AO = {}
        for l in open(f"{SP}/corte_schema/data/ans_t2.jsonl"):
            r = json.loads(l)
            if r["arm"] == "new" and r["regime"] == reg:
                AO[r["id"]] = r
    out = {}
    for i in SN:
        same = SN[i].get("state") == SO[i].get("state") and SN[i].get("decided") == SO[i].get("decided")
        out[i] = verdict(SN[i], AO.get(i) if same else AN.get(i))
    return out, SN


def rrich(reg, SN):
    P = load(f"{HERE}/preds/rrich.{reg}.jsonl")
    return {i: verdict(SN[i], P[i]) for i in SN}, P


def metrics(V, ids):
    ben = [i for i in ids if not truth(i)[0]]
    rk = [i for i in ids if truth(i)[0]]
    fa = sum(bool(V[i][0]) for i in ben)
    rec = sum(bool(V[i][0]) for i in rk)
    ex = sum(1 for i in rk if V[i][0] and V[i][1] == truth(i)[1])
    acc = sum(1 for i in ids if bool(V[i][0]) == truth(i)[0])
    unans = sum(1 for i in ids if V[i][0] is None)
    return dict(acc=acc / len(ids), acc_n=acc, n=len(ids), recall=rec / len(rk), rec_n=rec, risky=len(rk),
                fa=fa / len(ben), fa_n=fa, benign=len(ben), exact=ex, unans=unans)


def fmt(name, m):
    return (f"{name:<16} acc {m['acc']:.3f} ({m['acc_n']}/{m['n']})  recall {m['recall']:.3f} ({m['rec_n']}/{m['risky']})  "
            f"FA {m['fa']:.3f} ({m['fa_n']}/{m['benign']})  reason exact {m['exact']}/{m['rec_n']}"
            + (f"  unanswered {m['unans']}" if m["unans"] else ""))


def mcnemar2(b, c):
    n = b + c
    if not n:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, j) for j in range(0, k + 1)) / 2 ** n)


def run(reg, sens=False):
    E, SN = ekb(reg, sens)
    R, P = rrich(reg, SN)
    ids = sorted(L)
    AND = {i: ((bool(E[i][0]) and bool(R[i][0])), E[i][1] if E[i][0] and R[i][0] else None) for i in ids}
    OR = {i: ((bool(E[i][0]) or bool(R[i][0])), E[i][1] if E[i][0] else R[i][1]) for i in ids}
    tag = f"regime {reg}" + (" (sensitivity: ans_t2 + p2 changed)" if sens else "")
    print(f"== {tag}")
    me, mr = metrics(E, ids), metrics(R, ids)
    for name, V in (("EKB 0.1.20", E), ("R_RICH", R), ("R_RICH AND EKB", AND), ("R_RICH OR EKB", OR)):
        print(" ", fmt(name, metrics(V, ids)))
    ok_e = {i: bool(E[i][0]) == truth(i)[0] for i in ids}
    ok_r = {i: bool(R[i][0]) == truth(i)[0] for i in ids}
    b = sum(ok_e[i] and not ok_r[i] for i in ids)
    c = sum(ok_r[i] and not ok_e[i] for i in ids)
    d = me["acc"] - mr["acc"]
    rng = random.Random(20261011)
    diffs = []
    for _ in range(10000):
        s = [rng.choice(ids) for _ in ids]
        diffs.append(sum(ok_e[i] - ok_r[i] for i in s) / len(s))
    diffs.sort()
    lo, hi = diffs[249], diffs[9749]
    print(f"  delta acc EKB - R_RICH = {d * 100:+.1f} pp, 95% CI [{lo * 100:+.1f}, {hi * 100:+.1f}] pp; "
          f"McNemar: EKB right only {b}, R_RICH right only {c}, p = {mcnemar2(b, c):.3f}")
    if d >= 0.02 and lo > 0:
        verdict_ = "H1: the model adds beyond the facts"
    elif -0.02 < d < 0.02:
        verdict_ = "TIE: the value is in the facts"
    elif d <= -0.02:
        verdict_ = "the rule is better"
    else:
        verdict_ = "inconclusive, model ahead numerically (CI includes 0)"
    print(f"  pre-registered outcome: {verdict_}")
    if not sens:
        print("  discordant items (truth | EKB | R_RICH | rule's why):")
        for i in ids:
            if ok_e[i] != ok_r[i] or (truth(i)[0] and E[i][0] and R[i][0] and E[i][1] != R[i][1]):
                w = "; ".join(P[i]["why"])[:160]
                print(f"    {'EKB' if ok_e[i] and not ok_r[i] else ('RULE' if ok_r[i] and not ok_e[i] else 'why ')} "
                      f"{i} | {truth(i)[1]} | {E[i][1] if E[i][0] else 'ok'} | {R[i][1] if R[i][0] else 'ok'} | {w}")
        both = [i for i in ids if not ok_e[i] and not ok_r[i]]
        print(f"  both wrong ({len(both)}):")
        for i in both:
            print(f"    {i} | {truth(i)[1]} | {E[i][1] if E[i][0] else 'ok'} | {R[i][1] if R[i][0] else 'ok'}")
    return d, lo, hi


for reg in "RN":
    run(reg)
for reg in "RN":
    run(reg, sens=True)
