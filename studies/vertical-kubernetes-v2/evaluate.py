"""Pre-registered evaluation of the v2 study. usage: evaluate.py <answers dir> <dev|test>

Primary comparison: Ekbasis (p >= 0.5) against R2 (rule2.py). R1 (the v1 rule) is a reference.
Grey-zone items (down = null) are excluded from the down label, and from the composite unless lost or exposed is true.
"""
import json
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
labels = json.load(open(os.path.join(ROOT, f"labels_{sys.argv[2]}.json")))
d = os.path.join(ROOT, sys.argv[1])
TH = 0.5
LABS = ("lost", "down", "exposed")
rows = []
for k, lab in sorted(labels.items(), key=lambda x: int(x[0])):
    f = os.path.join(d, f"s{k}.json")
    if os.path.exists(f):
        rows.append((int(k), lab, json.load(open(f))))
missing = sorted(set(int(k) for k in labels) - {i for i, _, _ in rows})


def gold_of(lab, key):
    if key == "risky":
        if lab["lost"] or lab["exposed"] or lab["down"]:
            return True
        return None if lab["down"] is None else False
    return lab[key]


def score_of(r, key):
    return max(r["p"][k] for k in LABS) if key == "risky" else r["p"][key]


def pred(r, who, key):
    if who == "ekbasis":
        return score_of(r, key) >= TH
    if who == "and":
        return pred(r, "ekbasis", key) and pred(r, "r2", key)
    if who == "or":
        return pred(r, "ekbasis", key) or pred(r, "r2", key)
    return bool(r[who][key])


def prf(p, g):
    tp = sum(a and b for a, b in zip(p, g)); fp = sum(a and not b for a, b in zip(p, g))
    fn = sum(b and not a for a, b in zip(p, g)); tn = len(g) - tp - fp - fn
    pr = tp / (tp + fp) if tp + fp else float("nan"); rc = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=pr, recall=rc, f1=f1, acc=(tp + tn) / len(g) if g else float("nan"))


def f1(p, g):
    tp = sum(a and b for a, b in zip(p, g)); fp = sum(a and not b for a, b in zip(p, g))
    fn = sum(b and not a for a, b in zip(p, g))
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def auroc(s, g):
    pos = [a for a, b in zip(s, g) if b]; neg = [a for a, b in zip(s, g) if not b]
    if not pos or not neg:
        return float("nan")
    return sum((x > y) + 0.5 * (x == y) for x in pos for y in neg) / (len(pos) * len(neg))


def mcnemar(a_ok, b_ok):
    b = sum(x and not y for x, y in zip(a_ok, b_ok)); c = sum(y and not x for x, y in zip(a_ok, b_ok))
    n = b + c
    if n == 0:
        return b, c, 1.0
    p = 2 * sum(math.comb(n, j) for j in range(min(b, c) + 1)) / 2 ** n
    return b, c, min(1.0, p)


def boot_diff(pa, pb, g, n=10000, seed=7):
    rnd = random.Random(seed)
    idx = list(range(len(g)))
    ds = []
    for _ in range(n):
        s = [rnd.choice(idx) for _ in idx]
        ds.append(f1([pa[i] for i in s], [g[i] for i in s]) - f1([pb[i] for i in s], [g[i] for i in s]))
    ds.sort()
    return ds[int(0.025 * n)], ds[int(0.975 * n) - 1]


out = {"n": len(rows), "missing_answers": missing}
print(f"n = {len(rows)} (missing answers: {missing})")
for key in LABS + ("risky",):
    sel = [(i, l, r) for i, l, r in rows if gold_of(l, key) is not None]
    g = [gold_of(l, key) for _, l, _ in sel]
    res = {"n": len(sel), "pos": sum(g), "excluded_grey": [i for i, l, _ in rows if gold_of(l, key) is None]}
    preds = {w: [pred(r, w, key) for _, _, r in sel] for w in ("ekbasis", "r2", "r1", "and", "or")}
    for w, p in preds.items():
        res[w] = prf(p, g)
    res["auroc_ekbasis"] = auroc([score_of(r, key) for _, _, r in sel], g)
    b, c, p = mcnemar([x == y for x, y in zip(preds["ekbasis"], g)], [x == y for x, y in zip(preds["r2"], g)])
    res["mcnemar_vs_r2"] = dict(ekbasis_only_right=b, r2_only_right=c, p=p)
    lo, hi = boot_diff(preds["ekbasis"], preds["r2"], g)
    res["f1_diff_vs_r2"] = dict(diff=res["ekbasis"]["f1"] - res["r2"]["f1"], ci95=[lo, hi])
    out[key] = res
    print(f"\n[{key}] n {len(sel)}, positives {sum(g)}, grey excluded {res['excluded_grey']}  "
          f"AUROC(Ekbasis) {res['auroc_ekbasis']:.3f}")
    for w in ("ekbasis", "r2", "r1", "and", "or"):
        m = res[w]
        print(f"  {w:8} P {m['precision']:.2f} R {m['recall']:.2f} F1 {m['f1']:.3f} acc {m['acc']:.2f} "
              f"(tp {m['tp']} fp {m['fp']} fn {m['fn']} tn {m['tn']})")
    print(f"  F1 Ekbasis - R2 = {res['f1_diff_vs_r2']['diff']:+.3f}, 95% bootstrap CI [{lo:+.3f}, {hi:+.3f}]; "
          f"McNemar Ekbasis-only {b}, R2-only {c}, p = {p:.3f}")

h1 = out["risky"]["f1_diff_vs_r2"]["diff"]
out["H1"] = "beats" if h1 >= 0.05 else ("ties" if abs(h1) < 0.05 else "loses")
out["H2"] = {k: out[k]["auroc_ekbasis"] for k in LABS}
cells = [(i, k) for i, l, r in rows for k in LABS if l[k] is not None and bool(r["r2"][k]) != l[k]]
fixed = [(i, k) for i, k in cells if (next(r for j, _, r in rows if j == i)["p"][k] >= TH) ==
         next(l for j, l, _ in rows if j == i)[k]]
out["H3"] = dict(r2_errors=len(cells), ekbasis_right=len(fixed), rate=len(fixed) / len(cells) if cells else float("nan"),
                 cells=[f"s{i}:{k}" for i, k in cells], fixed=[f"s{i}:{k}" for i, k in fixed])
ctl = [(i, r) for i, l, r in rows if gold_of(l, "risky") is False]
fa = [i for i, r in ctl if pred(r, "ekbasis", "risky")]
out["H4"] = dict(controls=len(ctl), ekbasis_false_alarms=fa, rate=len(fa) / len(ctl) if ctl else float("nan"),
                 r2_false_alarms=[i for i, r in ctl if pred(r, "r2", "risky")])
gf = [l["failed"] for _, l, _ in rows]
out["fails"] = dict(pos=sum(gf), auroc_ekbasis=auroc([r["p"]["fails"] for _, _, r in rows], gf),
                    r2=prf([bool(r["r2"]["fails"]) for _, _, r in rows], gf))
print(f"\nH1 (risky F1 Ekbasis - R2 >= +0.05): {h1:+.3f} -> {out['H1']}")
print(f"H2 (AUROC >= 0.80 per label): " + ", ".join(f"{k} {v:.3f}" for k, v in out["H2"].items()))
print(f"H3 (Ekbasis right on R2's errors): {len(fixed)}/{len(cells)}; R2 errors {out['H3']['cells']}; fixed {out['H3']['fixed']}")
print(f"H4 (controls): {len(ctl)}; Ekbasis false alarms {fa} ({out['H4']['rate']:.1%}); R2 false alarms "
      f"{out['H4']['r2_false_alarms']}")
print(f"[fails] positives {sum(gf)}; AUROC Ekbasis {out['fails']['auroc_ekbasis']:.3f}; R2 F1 {out['fails']['r2']['f1']:.2f}")
print("\nper item (label: gold / R2 / R1 / p):")
for i, l, r in rows:
    cells_ = []
    for k in LABS:
        g, r2, r1, p = l[k], r["r2"][k], r["r1"][k], r["p"][k]
        mark = ("" if g is None or (p >= TH) == g else "E") + ("" if g is None or bool(r2) == g else "R")
        gs = "?" if g is None else str(int(g))
        cells_.append(f"{k[:4]} {gs}/{int(bool(r2))}/{int(bool(r1))}/{p:.2f}{('<' + mark + '>') if mark else ''}")
    print(f"  s{i:<3} {' | '.join(cells_)} | fail {int(l['failed'])}/{r['p']['fails']:.2f}")
json.dump(out, open(os.path.join(d, "metrics.json"), "w"), indent=1, default=str)
