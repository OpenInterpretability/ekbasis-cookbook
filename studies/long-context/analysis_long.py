"""Long-context study: the registered analysis (PREREG.md section 6). No model calls.

    venv/bin/python analysis_long.py > results.txt
"""
import json, math, os, random, statistics as st, sys

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(os.path.dirname(HERE), "v4", "data")
T = 0.5
B = 10_000
LONG = ["16k", "32k", "64k", "120k"]


def load(p):
    if not os.path.exists(p):
        return {}
    out = {}
    for l in open(p):
        r = json.loads(l)
        out[r["id"]] = r
    return out


LAB = {r["id"]: r for r in map(json.loads, open(os.path.join(V4, "labels_v3.jsonl")))}
ITEMS = {r["id"]: r for r in json.load(open(os.path.join(HERE, "data", "items.json")))["items"]}
IDS = sorted(LAB)


def truth(i):
    lp = LAB[i]["label_product"]
    return bool(lp["lost"] or lp["fails"])


def verdict(i, a):
    """(risky, answered). No usable answer: cannot foresee = risky (fail closed), as the product does."""
    if a is None or "error" in a:
        return True, False
    pf, pl = a["p_fails"], a["p_lost"]
    if ITEMS[i]["schema_error_autocommit"]:
        pf = 1.0
    return (pf >= T or pl >= T), True


def auroc(ys, ps):
    pos = [p for y, p in zip(ys, ps) if y]
    neg = [p for y, p in zip(ys, ps) if not y]
    if not pos or not neg:
        return float("nan")
    s = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg)
    return s / (len(pos) * len(neg))


def brier(ys, ps):
    return sum((p - y) ** 2 for y, p in zip(ys, ps)) / len(ys)


def ece(ys, ps, bins=10):
    tot = 0.0
    for b in range(bins):
        idx = [k for k, p in enumerate(ps) if (b / bins <= p < (b + 1) / bins) or (b == bins - 1 and p == 1.0)]
        if idx:
            tot += len(idx) / len(ps) * abs(sum(ps[k] for k in idx) / len(idx) - sum(ys[k] for k in idx) / len(idx))
    return tot


def mcnemar(b, c):
    n, k = b + c, min(b, c)
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(math.ceil(q * len(xs))) - 1))]


def boot(fn, n, seed=20261011):
    rng = random.Random(seed)
    vals = sorted(fn([rng.randrange(n) for _ in range(n)]) for _ in range(B))
    vals = [v for v in vals if not math.isnan(v)]
    return pct(vals, 0.025), pct(vals, 0.975)


def qmetrics(ids, A, q):
    key = {"lost": "lost", "fails": "fails"}[q]
    rows = [(LAB[i]["label_product"][key], A[i][f"p_{q}"]) for i in ids if A.get(i) and "error" not in A[i]]
    ys, ps = [y for y, _ in rows], [p for _, p in rows]
    return auroc(ys, ps), brier(ys, ps), ece(ys, ps), len(rows)


def compare(name, ids, A0, A1, show_depth=False):
    v0 = {i: verdict(i, A0.get(i)) for i in ids}
    v1 = {i: verdict(i, A1.get(i)) for i in ids}
    ok0 = [v0[i][0] == truth(i) for i in ids]
    ok1 = [v1[i][0] == truth(i) for i in ids]
    n = len(ids)
    acc0, acc1 = sum(ok0) / n, sum(ok1) / n
    risky = [i for i in ids if truth(i)]
    ben = [i for i in ids if not truth(i)]
    rec0, rec1 = sum(v0[i][0] for i in risky), sum(v1[i][0] for i in risky)
    fa0, fa1 = sum(v0[i][0] for i in ben), sum(v1[i][0] for i in ben)
    b = sum(1 for k in range(n) if ok0[k] and not ok1[k])     # worse at length
    c = sum(1 for k in range(n) if ok1[k] and not ok0[k])     # better at length
    drop = acc0 - acc1
    ci = boot(lambda idx: sum(ok0[k] - ok1[k] for k in idx) / len(idx), n)
    unanswered = sum(1 for i in ids if not v1[i][1])
    print(f"\n== {name} vs L0 (n={n}, unanswered at length {unanswered}, counted as cannot foresee = risky)")
    print(f"accuracy L0 {acc0:.3f} -> {acc1:.3f}; drop {drop * 100:+.1f} pp [95% CI {ci[0] * 100:+.1f}, {ci[1] * 100:+.1f}]; "
          f"worse {b}, better {c}, McNemar p={mcnemar(b, c):.3f}")
    print(f"recall {rec0}/{len(risky)} -> {rec1}/{len(risky)}; false alarms {fa0}/{len(ben)} -> {fa1}/{len(ben)}")
    res = {"drop": drop, "ci_hi": ci[1], "rec0": rec0, "rec1": rec1, "fa0": fa0, "fa1": fa1, "auroc_drop": {}}
    for q in ("lost", "fails"):
        a0, b0, e0, n0 = qmetrics(ids, A0, q)
        a1, b1, e1, n1 = qmetrics(ids, A1, q)
        pair = [i for i in ids if A0.get(i) and A1.get(i) and "error" not in A0[i] and "error" not in A1[i]]
        ys = [LAB[i]["label_product"][q] for i in pair]
        p0 = [A0[i][f"p_{q}"] for i in pair]
        p1 = [A1[i][f"p_{q}"] for i in pair]
        cd = boot(lambda idx: auroc([ys[k] for k in idx], [p0[k] for k in idx]) -
                  auroc([ys[k] for k in idx], [p1[k] for k in idx]), len(pair))
        d = [abs(x - y) for x, y in zip(p0, p1)]
        flips = sum((x >= T) != (y >= T) for x, y in zip(p0, p1))
        res["auroc_drop"][q] = a0 - a1
        print(f"  Q_{q.upper():5s} AUROC {a0:.3f} -> {a1:.3f} (drop {a0 - a1:+.3f} [{cd[0]:+.3f},{cd[1]:+.3f}]); "
              f"Brier {b0:.3f} -> {b1:.3f}; ECE {e0:.3f} -> {e1:.3f}; |dp| median {st.median(d):.3f} p90 {pct(d, .9):.3f} "
              f"max {max(d):.3f}, >0.10 in {sum(x > 0.1 for x in d)}/{len(d)}; crosses 0.5 in {flips}; "
              f"mean p {st.mean(p0):.3f} -> {st.mean(p1):.3f}")
    if show_depth:
        for dp in ("start", "middle", "end"):
            sub = [k for k, i in enumerate(ids) if ITEMS[i]["depth_long"] == dp]
            w = sum(1 for k in sub if ok0[k] and not ok1[k])
            bt = sum(1 for k in sub if ok1[k] and not ok0[k])
            print(f"  depth {dp:6s} n={len(sub)}: accuracy {sum(ok0[k] for k in sub) / len(sub):.3f} -> "
                  f"{sum(ok1[k] for k in sub) / len(sub):.3f} (worse {w}, better {bt}); "
                  f"recall {sum(v1[ids[k]][0] for k in sub if truth(ids[k]))}/{sum(truth(ids[k]) for k in sub)} "
                  f"(L0 {sum(v0[ids[k]][0] for k in sub if truth(ids[k]))}); false alarms "
                  f"{sum(v1[ids[k]][0] for k in sub if not truth(ids[k]))} (L0 {sum(v0[ids[k]][0] for k in sub if not truth(ids[k]))})")
    return res


def passes(r):
    c = {"C1 accuracy drop <= 2 pp and CI upper <= 4 pp": r["drop"] <= 0.02 and r["ci_hi"] <= 0.04,
         "C2 AUROC drop <= 0.02 (Q_LOST and Q_FAILS)": all(v <= 0.02 for v in r["auroc_drop"].values()),
         "C3 recall >= L0 - 2 items": r["rec1"] >= r["rec0"] - 2,
         "C4 false alarms <= L0 + 3 items": r["fa1"] <= r["fa0"] + 3}
    return c


def latency():
    C = load(os.path.join(HERE, "ans", "cold.jsonl"))
    if not C:
        return
    print("\n== Cold latency (unique distractors, no prefix shared with any other request; 2 questions per request)")
    for c in ["L0"] + LONG:
        rs = [r for r in C.values() if r.get("cond") == c and "error" not in r]
        if not rs:
            continue
        secs = [r["secs"] for r in rs]
        model = [r["timing"].get("model", float("nan")) / 1000 for r in rs]
        queue = [r["timing"].get("queue", 0) / 1000 for r in rs]
        toks = [r["usage"]["input_tokens"] for r in rs]
        print(f"{c:5s} n={len(rs)} input tokens (both sequences) median {st.median(toks):,.0f}; wall s median "
              f"{st.median(secs):.1f} (min {min(secs):.1f}, max {max(secs):.1f}); model s median {st.median(model):.1f}; "
              f"queue s max {max(queue):.1f}")


def main():
    A = {c: load(os.path.join(HERE, "ans", f"{c}.jsonl")) for c in ["L0", "L0h"] + LONG}
    print(f"items {len(IDS)}; risky {sum(map(truth, IDS))}; answered: " +
          ", ".join(f"{c} {sum(1 for r in A[c].values() if 'error' not in r)}" for c in A))
    for c in ["L0"] + ["L0h"] + LONG:
        toks = [r["usage"]["input_tokens"] / 2 for r in A[c].values() if r.get("usage")]
        if toks:
            print(f"  {c:5s} input tokens per sequence (usage / 2): median {st.median(toks):,.0f}, min {min(toks):,.0f}, "
                  f"max {max(toks):,.0f}")
    print(f"total input tokens used: {sum((r.get('usage') or {}).get('input_tokens', 0) for c in A for r in A[c].values()) + sum((r.get('usage') or {}).get('input_tokens', 0) for r in load(os.path.join(HERE, 'ans', 'cold.jsonl')).values()):,}")
    if A["L0h"]:
        compare("L0h (long header, no distractors; control)", [i for i in IDS if i in A["L0h"]], A["L0"], A["L0h"])
    verdicts = {}
    for c in LONG:
        if not A[c]:
            print(f"\n== {c}: not run")
            continue
        ids = [i for i in IDS if i in A[c]]
        r = compare(c, ids, A["L0"], A[c], show_depth=c in ("64k", "120k"))
        crit = passes(r)
        for k, v in crit.items():
            print(f"  {k}: {'PASS' if v else 'FAIL'}")
        full = len(ids) == len(IDS)
        verdicts[c] = all(crit.values()) and full
        print(f"  -> {c}: {'NON-INFERIOR' if all(crit.values()) else 'NOT non-inferior'}"
              + ("" if full else f" (EXPLORATORY: subsample n={len(ids)}, cannot be the ceiling)"))
        if not full and A["64k"]:
            compare(f"64k on the same {len(ids)} items (context for {c})", ids, A["L0"], A["64k"])
    ceiling = "L0 (none of the lengths)"
    for c in LONG:
        if verdicts.get(c):
            ceiling = c
        else:
            break
    print(f"\n== Registered decision: ceiling = {ceiling} (largest length that passes, with every shorter one passing)")
    sys.path.insert(0, os.path.join(HERE, "ekbasis"))
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(os.path.join(HERE, "tok", "tokenizer.json"))
    r = sorted(len(tok.encode(q["state"]).ids) / len(q["state"]) for q in map(json.loads, open(os.path.join(HERE, "data", "req_L0.jsonl"))))
    q99, med = pct(r, 0.99), st.median(r)
    print(f"tokens per character in the 184 L0 states: median {med:.3f}, q99 {q99:.3f}, max {r[-1]:.3f}")
    for c, L in (("16k", 16000), ("32k", 32000), ("64k", 64000), ("120k", 120000)):
        print(f"  MAX_CHARS for {c}: q99 rule {int((L - 500) / q99):,}; median rule {int((L - 500) / med):,}")
    print(f"  the current MAX_CHARS 60,000 is {60000 * q99:,.0f} tokens at q99, {60000 * med:,.0f} at the median")
    latency()


if __name__ == "__main__":
    main()
