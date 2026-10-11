"""Held-out scoring (PREREG_fw.md). Reads labels. python3 score_fw.py > results_fw.txt"""
import glob, json, os, random, sys
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__)); SP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import load_fw as LF, rule, rule_noseed   # noqa: E402  (first: they need the 0.1.20 clone of ekbasis)
sys.path.insert(1, os.path.join(SP, "fw_eval")); sys.path.insert(1, os.path.join(SP, "fw_eval5"))
import analysis_v5 as A5          # noqa: E402  frozen product mapping (v6 has the same code); its M is the clone
V4 = A5.V4

PRED = {"v5": os.path.join(SP, "fw_eval5/preds/v5.jsonl"), "v6": os.path.join(SP, "fw_eval_rails/preds/v6.jsonl")}


def labelled(ev):
    d = LF.EVALS[ev][0]
    out = {}
    for p in glob.glob(os.path.join(SP, d, "data", "items", "*.jsonl")):
        for l in open(p):
            r = json.loads(l)
            out[f"{r['project']}/{r['path']}"] = r
    return out


def rule_verdict(r, f, mod):
    if f is None:                                   # decided by the product: same verdict in every arm
        return A5.product(r, None)
    kind = mod.decide(f)[0]
    se = bool(r["product"].get("schema_error"))
    if se or kind == "fails":
        return True, "fails"
    if kind == "loses":
        return True, "loses"
    return False, "ok"


def mcnemar2(b, c):
    n = b + c
    return min(1.0, 2 * sum(comb(n, j) for j in range(min(b, c) + 1)) / 2 ** n) if n else 1.0


def stats(ids, V, T, warn=None):
    ben = [i for i in ids if not T[i][0]]; rk = [i for i in ids if T[i][0]]
    fa = sum(bool(V[i][0]) for i in ben); rec = sum(bool(V[i][0]) for i in rk)
    ex = sum(1 for i in rk if V[i][0] and V4.ok_kind(V[i][1], T[i][1]))
    acc = sum(bool(V[i][0]) == T[i][0] for i in ids)
    s = (f"acc {acc / len(ids):.3f} ({acc}/{len(ids)})  recall {rec}/{len(rk)} = {rec / max(len(rk), 1):.3f}  "
         f"FA {fa}/{len(ben)} = {fa / max(len(ben), 1):.3f}  reason exact {ex}/{rec}")
    out = dict(acc=acc / len(ids), fa=fa / max(len(ben), 1), rec=rec / max(len(rk), 1), recw=rec / max(len(rk), 1),
               warn_ben=0)
    if warn is not None:
        rw = sum(1 for i in rk if V[i][0] or warn[i]); wb = sum(1 for i in ben if warn[i] and not V[i][0])
        s += f"  | recall with warnings {rw}/{len(rk)} = {rw / max(len(rk), 1):.3f}  warnings on benign {wb}/{len(ben)}"
        out.update(recw=rw / max(len(rk), 1), warn_ben=wb)
    return s, out


def compare(ids, A, B, T, nameA, nameB):
    okA = {i: bool(A[i][0]) == T[i][0] for i in ids}; okB = {i: bool(B[i][0]) == T[i][0] for i in ids}
    b = sum(okA[i] and not okB[i] for i in ids); c = sum(okB[i] and not okA[i] for i in ids)
    d = (sum(okA.values()) - sum(okB.values())) / len(ids)
    rng = random.Random(20261011); ds = []
    for _ in range(10000):
        s = [rng.choice(ids) for _ in ids]
        ds.append(sum(okA[i] - okB[i] for i in s) / len(s))
    ds.sort(); lo, hi = ds[249], ds[9749]
    if d >= 0.02 and lo > 0:
        o = "H1: the model adds"
    elif -0.02 < d < 0.02:
        o = "TIE"
    elif d <= -0.02:
        o = "the rule is better"
    else:
        o = "inconclusive"
    return (f"{nameA} - {nameB}: {d * 100:+.1f} pp [{lo * 100:+.1f}, {hi * 100:+.1f}]; McNemar {nameA} only {b}, "
            f"{nameB} only {c}, p = {mcnemar2(b, c):.3f} -> {o}")


def main():
    arms = {k: {} for k in ("a EKB", "b R_RICH", "c R_NOSEED", "d POLICY", "e NOSEED OR EKB")}
    warn, T, fw, sent, unconv = {}, {}, {}, {}, []
    for ev in ("v5", "v6"):
        rows, states = LF.items(ev)
        lab = labelled(ev)
        preds = {p["id"]: p for p in map(json.loads, open(PRED[ev])) if "error" not in p}
        for r in rows:
            e = A5.product(r, preds.get(r["id"]))
            if e[1] == "code_not_foreseen":
                continue
            f = None
            if not r["product"]["decided"]:
                try:
                    f = LF.facts_for(r, states)
                except LF.A.Unconvertible:
                    unconv.append(r["id"]); continue
            i = r["id"]
            T[i] = V4.truth(lab[i]); fw[i] = r["framework"]; sent[i] = f is not None
            arms["a EKB"][i] = e
            arms["b R_RICH"][i] = rule_verdict(r, f, rule)
            c = rule_verdict(r, f, rule_noseed)
            arms["c R_NOSEED"][i] = c
            arms["d POLICY"][i] = c
            warn[i] = bool(e[0]) and not c[0] and f is not None
            arms["e NOSEED OR EKB"][i] = c if c[0] else e
    print(f"unconvertible (out of both arms): {len(unconv)} {unconv[:5]}")
    groups = [("ALL (primary)", sorted(T))] + [(g, sorted(i for i in T if fw[i] == g)) for g in ("django", "alembic", "rails")] \
        + [("ALL, sent to the model (exploratory)", sorted(i for i in T if sent[i]))]
    summary = {}
    for g, ids in groups:
        print(f"\n== {g}: n = {len(ids)}, risky {sum(T[i][0] for i in ids)}")
        for k, V in arms.items():
            s, o = stats(ids, V, T, warn if k.startswith("d") else None)
            print(f"  {k:<16} {s}")
            if g.startswith("ALL (primary)"):
                summary[k] = o
        print("  " + compare(ids, arms["a EKB"], arms["c R_NOSEED"], T, "EKB", "R_NOSEED"))
        print("  " + compare(ids, arms["a EKB"], arms["b R_RICH"], T, "EKB", "R_RICH"))
    ekb_rec = summary["a EKB"]["rec"]
    elig = [(k, o) for k, o in summary.items() if not k.startswith("b") and o["fa"] <= 0.15 and o["recw"] >= ekb_rec - 1e-12]
    print("\n== product policy (PREREG_fw §6), aggregate")
    for k, o in summary.items():
        print(f"  {k:<16} acc {o['acc']:.3f}  FA {o['fa']:.3f}  recall with warnings {o['recw']:.3f} "
              f"(EKB {ekb_rec:.3f})  {'ELIGIBLE' if (k, o) in elig else ('not eligible' if not k.startswith('b') else 'not a candidate')}")
    if elig:
        best = sorted(elig, key=lambda x: (-x[1]["acc"], -x[1]["recw"], x[1]["warn_ben"]))[0]
        print(f"  chosen: {best[0]}")
    else:
        print("  no eligible policy")
    print("\n== errors, aggregate (truth | EKB | R_NOSEED | warn)")
    for i in sorted(T):
        e, c = arms["a EKB"][i], arms["c R_NOSEED"][i]
        if bool(e[0]) != T[i][0] or bool(c[0]) != T[i][0]:
            print(f"  {i} | {T[i][1]} | {e[1] if e[0] else 'ok'} | {c[1] if c[0] else 'ok'} | {'W' if warn[i] else ''}")


if __name__ == "__main__":
    main()
