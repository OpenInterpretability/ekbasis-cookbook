"""Step 7: the registered analysis (PREREG §6). usage: analysis.py dev|test [--threshold T] [--score max|any]

Population: labeled PRs (label 0/1) with facts and an Ekbasis answer. The rules are scored on the same PRs.
"""
import argparse
import json
import math
import os
import random

from ghc import ROOT

B = 2000
SEED = 7


def auroc(y, s):
    pos = [v for v, t in zip(s, y) if t == 1]
    neg = [v for v, t in zip(s, y) if t == 0]
    if not pos or not neg:
        return float("nan")
    w = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return w / (len(pos) * len(neg))


def conf(y, v):
    tp = sum(1 for a, b in zip(y, v) if a and b)
    fp = sum(1 for a, b in zip(y, v) if not a and b)
    fn = sum(1 for a, b in zip(y, v) if a and not b)
    tn = sum(1 for a, b in zip(y, v) if not a and not b)
    return tp, fp, fn, tn


def f1(y, v):
    tp, fp, fn, _ = conf(y, v)
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def metrics(y, v):
    tp, fp, fn, tn = conf(y, v)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "f1": round(f1(y, v), 3),
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "false_alarm": round(fp / (fp + tn), 3) if fp + tn else None,
            "accuracy": round((tp + tn) / len(y), 3)}


def cluster_boot(rows, stat):
    """95% percentile CI, resampling repositories (clusters) with replacement."""
    by = {}
    for r in rows:
        by.setdefault(r["repo"], []).append(r)
    keys = sorted(by)
    rng = random.Random(SEED)
    vals = []
    for _ in range(B):
        sample = [r for k in (rng.choice(keys) for _ in keys) for r in by[k]]
        v = stat(sample)
        if v == v:
            vals.append(v)
    vals.sort()
    return round(vals[int(0.025 * len(vals))], 3), round(vals[int(0.975 * len(vals)) - 1], 3)


def mcnemar_exact(y, va, vb):
    """Two-sided exact McNemar on correctness: b = A right & B wrong, c = A wrong & B right."""
    b = sum(1 for t, a, bb in zip(y, va, vb) if (a == t) and (bb != t))
    c = sum(1 for t, a, bb in zip(y, va, vb) if (a != t) and (bb == t))
    n = b + c
    if n == 0:
        return b, c, 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return b, c, min(1.0, 2 * p)


def load(split):
    lab = {f"{l['repo']}#{l['number']}": l for l in map(json.loads, open(os.path.join(ROOT, "data", f"{split}_labels.jsonl")))}
    facts = {d["id"]: d["facts"] for d in map(json.loads, open(os.path.join(ROOT, "data", f"{split}_facts.jsonl")))}
    ans = {d["id"]: d for d in map(json.loads, open(os.path.join(ROOT, "data", f"{split}_answers.jsonl"))) if "error" not in d}
    cands = {f"{x['repo']}#{x['number']}": x for x in map(json.loads, open(os.path.join(ROOT, "data", f"{split}_candidates.jsonl")))}
    rows = []
    for i, l in lab.items():
        if l["label"] is None or i not in ans or "error" in facts.get(i, {"error": 1}):
            continue
        F, a = facts[i], ans[i]
        major = F["delta"] == "major"
        rows.append({"id": i, "repo": l["repo"], "y": l["label"], "eco": cands[i]["eco"], "major": major,
                     "r1": major, "r2": major and F["breaking_word"],
                     "p_api": a["p_api"], "p_other": a["p_other"], "p_any": a["p_any"],
                     "s_max": max(a["p_api"], a["p_other"]), "usage": a.get("usage"), "timing": a.get("timing")})
    return rows, lab


def report(split, threshold, score):
    rows, lab = load(split)
    excl = {}
    for l in lab.values():
        if l["label"] is None:
            excl[l["excl"]] = excl.get(l["excl"], 0) + 1
    y = [r["y"] for r in rows]
    s = [r["s_max"] if score == "max" else r["p_any"] for r in rows]
    for r, v in zip(rows, s):
        r["s"] = v
        r["ek"] = v >= threshold
    out = {"split": split, "n": len(rows), "positives": sum(y), "excluded": excl, "score": score, "threshold": threshold,
           "repos": len({r["repo"] for r in rows})}
    out["auroc"] = round(auroc(y, s), 3)
    out["auroc_ci"] = cluster_boot(rows, lambda rs: auroc([r["y"] for r in rs], [r["s"] for r in rs]))
    for name, key in (("ekbasis", "ek"), ("rule_major", "r1"), ("rule_major_breaking", "r2")):
        out[name] = metrics(y, [r[key] for r in rows])
    best = "r1" if f1(y, [r["r1"] for r in rows]) >= f1(y, [r["r2"] for r in rows]) else "r2"
    for key in ("r1", "r2"):
        out[f"delta_f1_vs_{key}"] = round(f1(y, [r["ek"] for r in rows]) - f1(y, [r[key] for r in rows]), 3)
        out[f"delta_f1_vs_{key}_ci"] = cluster_boot(rows, lambda rs, key=key: f1([r["y"] for r in rs], [r["ek"] for r in rs])
                                                     - f1([r["y"] for r in rs], [r[key] for r in rs]))
        b, c, p = mcnemar_exact(y, [r["ek"] for r in rows], [r[key] for r in rows])
        out[f"mcnemar_vs_{key}"] = {"ek_right_rule_wrong": b, "ek_wrong_rule_right": c, "p": round(p, 4)}
    out["best_rule_on_this_split"] = best
    # secondary: the other scores, and ranking inside semver-major PRs and by ecosystem
    for k in ("p_api", "p_other", "p_any", "s_max"):
        out[f"auroc_{k}"] = round(auroc(y, [r[k] for r in rows]), 3)
    mj = [r for r in rows if r["major"]]
    out["major_n"], out["major_pos"] = len(mj), sum(r["y"] for r in mj)
    out["auroc_within_major"] = round(auroc([r["y"] for r in mj], [r["s"] for r in mj]), 3)
    out["auroc_within_major_ci"] = cluster_boot(mj, lambda rs: auroc([r["y"] for r in rs], [r["s"] for r in rs])) if mj else None
    nm = [r for r in rows if not r["major"]]
    out["nonmajor_n"], out["nonmajor_pos"] = len(nm), sum(r["y"] for r in nm)
    out["auroc_within_nonmajor"] = round(auroc([r["y"] for r in nm], [r["s"] for r in nm]), 3)
    for eco in ("npm", "pip"):
        er = [r for r in rows if r["eco"] == eco]
        out[f"{eco}_n"], out[f"{eco}_pos"] = len(er), sum(r["y"] for r in er)
        out[f"{eco}_auroc"] = round(auroc([r["y"] for r in er], [r["s"] for r in er]), 3)
        out[f"{eco}_ekbasis"] = metrics([r["y"] for r in er], [r["ek"] for r in er])
    # calibration (ECE, 10 equal-width bins) of the score
    bins = [[] for _ in range(10)]
    for r in rows:
        bins[min(9, int(r["s"] * 10))].append(r)
    out["ece"] = round(sum(len(b_) / len(rows) * abs(sum(r["s"] for r in b_) / len(b_) - sum(r["y"] for r in b_) / len(b_))
                           for b_ in bins if b_), 3)
    # threshold sweep (reported; the registered threshold is the one above)
    out["sweep"] = {t: metrics(y, [r["s"] >= t for r in rows])["f1"] for t in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)}
    toks = [r["usage"].get("prompt_tokens", 0) for r in rows if r.get("usage")]
    out["input_tokens_total"] = sum(toks)
    model_ms = sorted(r["timing"].get("model", 0) for r in rows if r.get("timing"))
    out["model_ms_median"] = model_ms[len(model_ms) // 2] if model_ms else None
    return out, rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--score", default="max", choices=("max", "any"))
    a = ap.parse_args()
    out, rows = report(a.split, a.threshold, a.score)
    print(json.dumps(out, indent=1))
