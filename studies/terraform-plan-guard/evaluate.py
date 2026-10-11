"""Pre-registered evaluation. usage: evaluate.py <answers dir>"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
labels = json.load(open(os.path.join(ROOT, "labels.json")))
d = os.path.join(ROOT, sys.argv[1])
rows = []
for k, lab in sorted(labels.items(), key=lambda x: int(x[0])):
    f = os.path.join(d, f"s{k}.json")
    if os.path.exists(f):
        r = json.load(open(f))
        rows.append((int(k), lab, r))
TH = 0.5


def prf(pred, gold):
    tp = sum(p and g for p, g in zip(pred, gold)); fp = sum(p and not g for p, g in zip(pred, gold))
    fn = sum(g and not p for p, g in zip(pred, gold)); tn = len(gold) - tp - fp - fn
    pr = tp / (tp + fp) if tp + fp else float("nan"); rc = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * pr * rc / (pr + rc) if pr + rc and not math.isnan(pr) and not math.isnan(rc) else 0.0
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=pr, recall=rc, f1=f1, acc=(tp + tn) / len(gold))


def auroc(scores, gold):
    pos = [s for s, g in zip(scores, gold) if g]; neg = [s for s, g in zip(scores, gold) if not g]
    if not pos or not neg:
        return float("nan")
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def mcnemar(a_ok, b_ok):
    b = sum(x and not y for x, y in zip(a_ok, b_ok)); c = sum(y and not x for x, y in zip(a_ok, b_ok))
    n = b + c
    if n == 0:
        return b, c, 1.0
    k = min(b, c)
    p = 2 * sum(math.comb(n, j) for j in range(k + 1)) / 2 ** n
    return b, c, min(1.0, p)


out = {"n": len(rows)}
print(f"n = {len(rows)}")
for lab in ("lost", "down", "exposed", "risky"):
    if lab == "risky":
        gold = [l["lost"] or l["down"] or l["exposed"] for _, l, _ in rows]
        score = [max(r["p"]["lost"], r["p"]["down"], r["p"]["exposed"]) for _, _, r in rows]
    else:
        gold = [l[lab] for _, l, _ in rows]
        score = [r["p"][lab] for _, _, r in rows]
    ek = [s >= TH for s in score]
    ru = [r["rule"][lab] for _, _, r in rows]
    m_ek, m_ru = prf(ek, gold), prf(ru, gold)
    au = auroc(score, gold)
    b, c, p = mcnemar([x == g for x, g in zip(ek, gold)], [x == g for x, g in zip(ru, gold)])
    out[lab] = dict(pos=sum(gold), ekbasis=m_ek, rule=m_ru, auroc=au, mcnemar=dict(ek_only_right=b, rule_only_right=c, p=p))
    print(f"\n[{lab}] positives {sum(gold)}/{len(gold)}  AUROC(Ekbasis) {au:.3f}")
    for name, m in (("Ekbasis", m_ek), ("rule", m_ru)):
        print(f"  {name:8} P {m['precision']:.2f} R {m['recall']:.2f} F1 {m['f1']:.2f} acc {m['acc']:.2f} "
              f"(tp {m['tp']} fp {m['fp']} fn {m['fn']} tn {m['tn']})")
    print(f"  McNemar: Ekbasis-only right {b}, rule-only right {c}, p = {p:.3f}")
gold_f = [l["failed"] for _, l, _ in rows]
out["fails_auroc"] = auroc([r["p"]["fails"] for _, _, r in rows], gold_f)
print(f"\n[fails] positives {sum(gold_f)}  AUROC {out['fails_auroc']:.3f}")
safe = [(i, r) for i, l, r in rows if not (l["lost"] or l["down"] or l["exposed"])]
fa = [i for i, r in safe if r["verdict"]["risky"]]
out["controls"] = dict(n=len(safe), false_alarms=fa, rate=len(fa) / len(safe) if safe else float("nan"))
print(f"\n[controls] {len(safe)} safe; Ekbasis false alarms {len(fa)} {fa}; rule false alarms "
      f"{[i for i, r in safe if r['rule']['risky']]}")
rule_wrong = [(i, l, r) for i, l, r in rows if any(r["rule"][k] != l[k] for k in ("lost", "down", "exposed"))]
fix = [(i, k) for i, l, r in rule_wrong for k in ("lost", "down", "exposed") if r["rule"][k] != l[k]]
fixed = [(i, k) for i, k in fix if (dict(rows_by := {x[0]: x for x in rows})[i][2]["p"][k] >= TH) == rows_by[i][1][k]]
out["complement"] = dict(rule_errors=len(fix), ekbasis_right_on_them=len(fixed),
                         items=[f"s{i}:{k}" for i, k in fix], fixed=[f"s{i}:{k}" for i, k in fixed])
print(f"\n[complement] rule label-errors {len(fix)}; Ekbasis right on {len(fixed)}: {out['complement']['fixed']}")
print("rule errors:", out["complement"]["items"])
print("\nper item (label: gold / rule / p):")
for i, l, r in rows:
    cells = []
    for k in ("lost", "down", "exposed"):
        g, ru, p = l[k], r["rule"][k], r["p"][k]
        mark = ("" if (p >= TH) == g else "E") + ("" if ru == g else "R")
        cells.append(f"{k[:4]} {int(g)}/{int(ru)}/{p:.2f}{('<' + mark + '>') if mark else ''}")
    print(f"  s{i:<3} {' | '.join(cells)} | fail {int(l['failed'])}/{r['p']['fails']:.2f}")
json.dump(out, open(os.path.join(d, "metrics.json"), "w"), indent=1, default=str)
