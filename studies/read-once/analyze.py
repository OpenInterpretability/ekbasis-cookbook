"""Scores ans/answers.jsonl against the frozen v3 labels (label_product), per regime, with the PREREG criteria.

    python analyze.py > results.txt
"""
import json, os, random, statistics as S
HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "v4")
T = 0.5
B = 10000
SEED = 20261011


def verdict(st, a):
    """The product's verdict (score_v4.verdict): fails first, then loses; schema error in autocommit -> fails."""
    pf, pl = a["p_fails"], a["p_lost"]
    if st.get("schema_error_autocommit"):
        pf = 1.0
    if pf >= T:
        return True, "fails"
    if pl >= T:
        return True, "loses"
    return False, None


def auroc(ps, ys):
    pos = [p for p, y in zip(ps, ys) if y]
    neg = [p for p, y in zip(ps, ys) if not y]
    if not pos or not neg:
        return None
    s = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg)
    return s / (len(pos) * len(neg))


def brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)


def ece(ps, ys, bins=10):
    tot = 0.0
    for b in range(bins):
        idx = [i for i, p in enumerate(ps) if (b / bins <= p < (b + 1) / bins) or (b == bins - 1 and p == 1.0)]
        if idx:
            tot += len(idx) / len(ps) * abs(sum(ps[i] for i in idx) / len(idx) - sum(ys[i] for i in idx) / len(idx))
    return tot


def main():
    labels = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(V4, "data", "labels_v3.jsonl"))}
    ans = {}
    for l in open(os.environ.get("ANS") or os.path.join(HERE, "ans", "answers.jsonl")):
        d = json.loads(l)
        if "error" not in d:
            ans[(d["id"], d["regime"], d["arm"])] = d
    passes = {}
    for reg in ("N", "R"):
        st = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(V4, "st", f"t2_old.{reg}.jsonl"))}
        ids = [i for i in labels if (i, reg, "sep") in ans and (i, reg, "once") in ans]
        missing = [i for i in labels if i not in ids]
        rows = []
        for i in ids:
            lp = labels[i]["label_product"]
            risky = bool(lp["lost"] or lp["fails"])
            why = "fails" if lp["fails"] else ("loses" if risky else None)
            v = {arm: verdict(st[i], ans[(i, reg, arm)]) for arm in ("sep", "once")}
            rows.append({"id": i, "risky": risky, "why": why, "v": v, "lab": labels[i]})
        print(f"===== regime {reg}: {len(ids)} paired items, {len(missing)} missing {missing[:5]}")
        m = {}
        for arm in ("sep", "once"):
            fa = sum(r["v"][arm][0] for r in rows if not r["risky"])
            rec = sum(r["v"][arm][0] for r in rows if r["risky"])
            exact = sum(1 for r in rows if r["risky"] and r["v"][arm][0] and r["v"][arm][1] == r["why"])
            acc = sum(r["v"][arm][0] == r["risky"] for r in rows)
            m[arm] = dict(fa=fa, rec=rec, exact=exact, acc=acc)
            nb, nr = sum(not r["risky"] for r in rows), sum(r["risky"] for r in rows)
            print(f"{arm.upper():5} accuracy {acc}/{len(rows)} = {acc / len(rows):.3f}; false alarms {fa}/{nb}; "
                  f"recall {rec}/{nr}; reason exact {exact}/{rec}")
        # paired bootstrap of the accuracy difference ONCE - SEP
        d = [(r["v"]["once"][0] == r["risky"]) - (r["v"]["sep"][0] == r["risky"]) for r in rows]
        rng = random.Random(SEED)
        boots = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(B))
        lo, hi = boots[int(0.025 * B)], boots[int(0.975 * B) - 1]
        diff = sum(d) / len(d)
        print(f"accuracy ONCE - SEP = {diff * 100:+.2f} pp, 95% paired bootstrap [{lo * 100:+.2f}, {hi * 100:+.2f}]; "
              f"discordant: ONCE right only {d.count(1)}, SEP right only {d.count(-1)}")
        for r in rows:
            if r["v"]["sep"] != r["v"]["once"]:
                print(f"  verdict differs: {r['id']} truth={'risky:' + r['why'] if r['risky'] else 'benign'} "
                      f"sep={r['v']['sep']} once={r['v']['once']}")
        # calibration per question
        dps = []
        for q, lab in (("lost", "lost"), ("fails", "fails"), ("half", "half_applied")):
            qi = [r for r in rows if f"p_{q}" in ans[(r["id"], reg, "sep")] and f"p_{q}" in ans[(r["id"], reg, "once")]]
            if not qi:
                continue
            key = "label" if q == "half" else "label_product"
            ys = [int(bool(r["lab"][key][lab])) for r in qi]
            for arm in ("sep", "once"):
                ps = [ans[(r["id"], reg, arm)][f"p_{q}"] for r in qi]
                a = auroc(ps, ys)
                print(f"  {q:5} {arm:4} n={len(qi)} pos={sum(ys)} AUROC={a if a is None else round(a, 3)} "
                      f"Brier={brier(ps, ys):.4f} ECE={ece(ps, ys):.4f}")
            dq = [abs(ans[(r["id"], reg, "once")][f"p_{q}"] - ans[(r["id"], reg, "sep")][f"p_{q}"]) for r in qi]
            dps += dq
            print(f"  {q:5} |dp| median {S.median(dq):.4f} p90 {sorted(dq)[int(0.9 * len(dq))]:.4f} max {max(dq):.4f}")
        qs = sorted(dps)
        med_dp = S.median(dps)
        print(f"|dp| all answers: n={len(dps)} median {med_dp:.4f} p75 {qs[int(.75 * len(qs))]:.4f} "
              f"p90 {qs[int(.9 * len(qs))]:.4f} p99 {qs[int(.99 * len(qs))]:.4f} max {qs[-1]:.4f}; "
              f">0.1: {sum(x > .1 for x in dps)}, >0.3: {sum(x > .3 for x in dps)}")
        # usage and latency
        u = {arm: [ans[(r["id"], reg, arm)]["usage"]["input_tokens"] for r in rows] for arm in ("sep", "once")}
        ratio = [o / s for o, s in zip(u["once"], u["sep"])]
        drop = 1 - S.median(u["once"]) / S.median(u["sep"])
        print(f"input tokens median SEP {S.median(u['sep'])} ONCE {S.median(u['once'])} -> drop {drop:.1%}; "
              f"per-item ratio median {S.median(ratio):.3f} (min {min(ratio):.3f}, max {max(ratio):.3f}); "
              f"totals SEP {sum(u['sep'])} ONCE {sum(u['once'])}")
        for name, f in (("client s", lambda a: a["secs"]), ("model ms", lambda a: (a.get("timing") or {}).get("model"))):
            for arm in ("sep", "once"):
                xs = sorted(x for x in (f(ans[(r["id"], reg, arm)]) for r in rows) if x is not None)
                print(f"  latency {name} {arm}: median {S.median(xs):.2f} p90 {xs[int(.9 * len(xs))]:.2f}")
        crit = {
            "C1 accuracy CI lower >= -2pp": lo >= -0.02,
            "C2 false alarms ONCE <= SEP+3": m["once"]["fa"] <= m["sep"]["fa"] + 3,
            "C3 recall ONCE >= SEP-2": m["once"]["rec"] >= m["sep"]["rec"] - 2,
            "C4 reason ONCE >= SEP-2": m["once"]["exact"] >= m["sep"]["exact"] - 2,
            "C5 median |dp| <= 0.05": med_dp <= 0.05,
            "G1 median usage drop >= 35%": drop >= 0.35,
            "complete (<= 5 missing)": len(missing) <= 5,
        }
        for k, v in crit.items():
            print(f"  {k}: {'PASS' if v else 'FAIL'}")
        passes[reg] = all(crit.values())
    print("DECISION:", "PASS (both regimes)" if all(passes.values()) else f"FAIL {passes}")


if __name__ == "__main__":
    main()
