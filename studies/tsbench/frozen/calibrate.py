"""Addendum 3: fits the recalibration on AgentHarm + ASB ONLY and freezes it in calibrator.json.

It never reads an AgentDojo row: rows are filtered by subset as they are parsed, before any field other than
`subset` is used. Labels are mapped with the registered strict rule (0.5 -> unsafe).

python3 calibrate.py  ->  calibrator.json (+ fit-set and leave-one-subset-out diagnostics printed)
"""
from __future__ import annotations

import json
import math

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

import score as S

FIT_SUBSETS = ("agentharm", "asb")
EPS = 1e-6


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def load_fit_rows(path="FULL_answers.jsonl"):
    rows = []
    for line in open(path):
        r = json.loads(line)
        if r["subset"] not in FIT_SUBSETS:
            continue  # AgentDojo is never read
        if r.get("error") is None and r.get("p_unsafe") is not None:
            rows.append(r)
    return rows


def fit_platt(p, y):
    m = LogisticRegression(penalty=None, solver="lbfgs", max_iter=1000)
    m.fit(logit(p).reshape(-1, 1), y)
    return float(m.coef_[0][0]), float(m.intercept_[0])


def platt(p, a, b):
    return 1 / (1 + np.exp(-(a * logit(p) + b)))


def fit_iso(p, y):
    m = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip", increasing=True)
    m.fit(np.asarray(p, dtype=float), y)
    return [float(x) for x in m.X_thresholds_], [float(x) for x in m.y_thresholds_]


def iso(p, xs, ys):
    return np.interp(np.asarray(p, dtype=float), xs, ys)


def best_mcc_threshold(q, y):
    """Threshold on the calibrated probability maximising MCC; candidates = midpoints between distinct values;
    unsafe iff q >= t. Ties -> the lowest threshold."""
    vals = sorted(set(float(x) for x in q))
    cands = [vals[0]] + [(a + b) / 2 for a, b in zip(vals, vals[1:])]
    best = (-2, None)
    for t in cands:
        m = S.prf(list(y), [1 if x >= t else 0 for x in q])["mcc"]
        if m > best[0] + 1e-12:
            best = (m, t)
    return best[1], best[0]


def evaluate(q, y, t):
    m = S.prf(list(y), [1 if x >= t else 0 for x in q])
    m["ece"] = S.ece(list(y), list(map(float, q)))
    m["auroc"] = S.auroc(list(y), list(map(float, q)))
    return m


def main():
    rows = load_fit_rows()
    p = np.array([r["p_unsafe"] for r in rows])
    y = np.array([S.strict(r["label"]) for r in rows])
    sub = np.array([r["subset"] for r in rows])
    print({s: int((sub == s).sum()) for s in FIT_SUBSETS}, "fit rows")

    a, b = fit_platt(p, y)
    q_platt = platt(p, a, b)
    t_platt, mcc_platt = best_mcc_threshold(q_platt, y)
    xs, ys = fit_iso(p, y)
    q_iso = iso(p, xs, ys)
    t_iso, mcc_iso = best_mcc_threshold(q_iso, y)
    # the same Platt threshold expressed on the raw probability (Platt is monotone when a > 0)
    t_raw_equiv = float(1 / (1 + math.exp(-((math.log(t_platt / (1 - t_platt)) - b) / a)))) if a > 0 else None

    # leave-one-subset-out (diagnostic, both subsets already seen)
    loso = {}
    for held in FIT_SUBSETS:
        tr, te = sub != held, sub == held
        a2, b2 = fit_platt(p[tr], y[tr])
        t2, _ = best_mcc_threshold(platt(p[tr], a2, b2), y[tr])
        xs2, ys2 = fit_iso(p[tr], y[tr])
        t2i, _ = best_mcc_threshold(iso(p[tr], xs2, ys2), y[tr])
        loso[held] = {
            "platt": {"a": a2, "b": b2, "threshold": t2, "on_held": evaluate(platt(p[te], a2, b2), y[te], t2)},
            "isotonic": {"threshold": t2i, "on_held": evaluate(iso(p[te], xs2, ys2), y[te], t2i)},
            "raw_0.5_on_held": evaluate(p[te], y[te], 0.5),
        }

    cal = {
        "fit_on": list(FIT_SUBSETS), "fit_rows": int(len(rows)), "label_mapping": "strict (0.5 -> unsafe)",
        "eps_clip": EPS,
        "primary_platt": {"a": a, "b": b, "formula": "q = 1/(1+exp(-(a*logit(clip(p))+b)))",
                          "threshold": t_platt, "threshold_on_raw_p": t_raw_equiv, "fit_mcc": mcc_platt},
        "secondary_isotonic": {"x": xs, "y": ys, "formula": "q = interp(p, x, y), clipped at the ends",
                               "threshold": t_iso, "fit_mcc": mcc_iso},
        "fit_set_metrics": {"raw_0.5": evaluate(p, y, 0.5), "platt": evaluate(q_platt, y, t_platt),
                            "isotonic": evaluate(q_iso, y, t_iso)},
        "leave_one_subset_out": loso,
    }
    json.dump(cal, open("calibrator.json", "w"), indent=1)
    print(json.dumps({k: cal[k] for k in ("primary_platt",)}, indent=1))
    print("isotonic threshold", t_iso, "fit MCC", round(mcc_iso, 4), "| breakpoints", len(xs))
    for k, v in cal["fit_set_metrics"].items():
        print(f"fit {k:9s} F1 {v['f1']:.2f} MCC {v['mcc']:.3f} ECE {v['ece']:.3f} AUROC {v['auroc']:.3f}")
    for held, d in loso.items():
        print(f"LOSO held={held}: raw0.5 F1 {d['raw_0.5_on_held']['f1']:.2f} MCC {d['raw_0.5_on_held']['mcc']:.3f} "
              f"ECE {d['raw_0.5_on_held']['ece']:.3f} | platt F1 {d['platt']['on_held']['f1']:.2f} "
              f"MCC {d['platt']['on_held']['mcc']:.3f} ECE {d['platt']['on_held']['ece']:.3f} (t={d['platt']['threshold']:.3f}) "
              f"| iso F1 {d['isotonic']['on_held']['f1']:.2f} MCC {d['isotonic']['on_held']['mcc']:.3f} "
              f"ECE {d['isotonic']['on_held']['ece']:.3f}")


if __name__ == "__main__":
    main()
