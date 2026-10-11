"""Step 3: label statistics, the rule baselines, and (once preds/ exists) the pre-registered tests (PREREG §5).

    .venv/bin/python analysis.py            # dataset + rules (no model needed)
    .venv/bin/python analysis.py --lists    # write the fixed pilot / GLM subsample id lists (once, before any model run)
"""
from __future__ import annotations

import glob
import json
import os
import random
import re
import sys
from collections import Counter

import rules as RU

ROOT = os.path.dirname(os.path.abspath(__file__))
SEED = 20261010
B = 2000
SYNTH_CAST = {"22P02", "22007", "22008", "22003", "22001"}   # invalid text repr., datetime, out of range, too long
TASKS = {"lost": "lost", "fails": "fails", "half": "half_applied"}


def load_items(included_only=False):
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "items", "*.jsonl"))):
        for l in open(p):
            it = json.loads(l)
            it["id"] = f"{it['repo']}/{it['mig']}"
            if included_only and it.get("excluded"):
                continue
            out.append(it)
    return out


MOVES = RU.MOVES


def mechanisms(it):
    """How the data was lost (from the run's lost_detail and the statements): rows_deleted, dropped, overwritten, cast,
    partial_copy (an earlier statement copied it, but not all of it arrived: depends on how the synthetic rows join)."""
    out = set()
    st = it["statements"]
    for table, col, n, reason in it["run"]["lost_detail"]:
        name = (col or table.split(".")[-1]).lower()
        pat = re.compile(r'(?<![\w$])"?' + re.escape(name) + r'"?(?![\w$])', re.I)
        copied = any(MOVES.search(s) and pat.search(s) and not re.match(r"^\s*UPDATE\s+\"?" + re.escape(table.split('.')[-1]) +
                                                                        r"\"?\s+SET\s+\"?" + re.escape(name), s, re.I)
                     for s in st)
        if col is None:
            out.add("partial_copy" if copied and any(re.search(r"\bDROP\s+TABLE\b", s, re.I) for s in st) else "rows_deleted")
        elif copied and any(re.search(r"\bDROP\s+(COLUMN\s+)?(IF\s+EXISTS\s+)?\"?" + re.escape(name), s, re.I) for s in st):
            out.add("partial_copy")
        elif any(re.search(r"\bDROP\s+(COLUMN\s+)?(IF\s+EXISTS\s+)?\"?" + re.escape(name) + r"\b", s, re.I) for s in st) \
                or any(re.search(r"\bDROP\s+TABLE\b[^;]*\b" + re.escape(table.split('.')[-1]) + r"\b", s, re.I) for s in st):
            out.add("dropped")
        elif any(re.match(r"^\s*(WITH\b.*)?UPDATE\b", s, re.I | re.S) and pat.search(s) for s in st):
            out.add("overwritten")
        elif any(RU.ALTER_TYPE.search(s) and pat.search(s) for s in st):
            out.add("cast")
        else:
            out.add("other")
    return sorted(out)


def synthetic_cast(it):
    """Some statement failed casting or fitting a synthetic value (a token where real rows hold JSON, an enum label, a
    number...): the failure, and any loss that follows it, may not happen with production data."""
    return any(e.split(":")[0] in SYNTH_CAST for _, e in it["run"]["errors"])


# ---------------------------------------------------------------- metrics

def auroc(y, s):
    pos = [x for x, t in zip(s, y) if t]
    neg = [x for x, t in zip(s, y) if not t]
    if not pos or not neg:
        return float("nan")
    allv = sorted((v, i) for i, v in enumerate(s))
    ranks, i = [0.0] * len(s), 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[allv[k][1]] = (i + j) / 2 + 1
        i = j + 1
    rp = sum(r for r, t in zip(ranks, y) if t)
    return (rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def prf(y, pred):
    tp = sum(1 for a, b in zip(y, pred) if a and b)
    fp = sum(1 for a, b in zip(y, pred) if not a and b)
    fn = sum(1 for a, b in zip(y, pred) if a and not b)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def brier(y, s):
    return sum((x - t) ** 2 for x, t in zip(s, y)) / len(y)


def ece(y, s, bins=10):
    tot, n = 0.0, len(y)
    for b in range(bins):
        idx = [i for i, x in enumerate(s) if (b / bins <= x < (b + 1) / bins) or (b == bins - 1 and x == 1.0)]
        if idx:
            tot += len(idx) / n * abs(sum(s[i] for i in idx) / len(idx) - sum(y[i] for i in idx) / len(idx))
    return tot


def cluster_boot(fn, groups, seed=SEED, b=B):
    """Resample whole repos (12 clusters): the sensitivity CI for items that share a codebase."""
    rng = random.Random(seed)
    keys = sorted(set(groups))
    by = {k: [i for i, g in enumerate(groups) if g == k] for k in keys}
    vals = []
    for _ in range(b):
        idx = [i for k in (rng.choice(keys) for _ in keys) for i in by[k]]
        v = fn(idx)
        if v == v:
            vals.append(v)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def boot(fn, n, seed=SEED, b=B):
    rng = random.Random(seed)
    vals = []
    for _ in range(b):
        idx = [rng.randrange(n) for _ in range(n)]
        v = fn(idx)
        if v == v:
            vals.append(v)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


# ---------------------------------------------------------------- lists for the model runs

def write_lists(items):
    rng = random.Random(f"{SEED}:pilot")
    ids = [it["id"] for it in items]
    rng.shuffle(ids)
    open(os.path.join(ROOT, "data", "pilot_ids.txt"), "w").write("\n".join(ids) + "\n")
    # GLM subsample: 60 items, stratified by the (lost, fails) cell, proportional with a floor of 8 per non-empty cell
    rng = random.Random(f"{SEED}:glm")
    cells = {}
    for it in items:
        cells.setdefault((it["label"]["lost"], it["label"]["fails"]), []).append(it["id"])
    n_total, pick = 60, []
    quota = {c: max(8, round(n_total * len(v) / len(items))) for c, v in cells.items()}
    while sum(quota.values()) > n_total:
        big = max(quota, key=lambda c: quota[c])
        quota[big] -= 1
    for c, v in sorted(cells.items()):
        pick += rng.sample(sorted(v), min(quota[c], len(v)))
    open(os.path.join(ROOT, "data", "glm_ids.txt"), "w").write("\n".join(sorted(pick)) + "\n")
    print(f"pilot list: {len(ids)} ids; GLM subsample: {len(pick)} ids, quotas {quota}")


# ---------------------------------------------------------------- report

def load_preds(name):
    p = os.path.join(ROOT, "preds", f"{name}.jsonl")
    if not os.path.exists(p):
        return {}
    return {r["id"]: r for r in map(json.loads, open(p)) if "error" not in r}


def evaluate(items, scores, task, label="", thr=0.5):
    y = [it["label"][TASKS[task]] for it in items]
    s = scores
    p, r, f = prf(y, [x >= thr for x in s])
    a = auroc(y, s)
    n = len(y)
    ci_a = boot(lambda idx: auroc([y[i] for i in idx], [s[i] for i in idx]), n)
    ci_f = boot(lambda idx: prf([y[i] for i in idx], [s[i] >= thr for i in idx])[2], n)
    return {"name": label, "n": n, "pos": sum(y), "auroc": a, "auroc_ci": ci_a, "prec": p, "rec": r, "f1": f,
            "f1_ci": ci_f, "brier": brier(y, s), "ece": ece(y, s)}


def fmt(m):
    return (f"{m['name']:<22} n={m['n']:3d} pos={m['pos']:3d}  AUROC {m['auroc']:.3f} [{m['auroc_ci'][0]:.3f},"
            f"{m['auroc_ci'][1]:.3f}]  P {m['prec']:.3f} R {m['rec']:.3f} F1 {m['f1']:.3f} [{m['f1_ci'][0]:.3f},"
            f"{m['f1_ci'][1]:.3f}]  Brier {m['brier']:.3f}")


def paired_f1_diff(items, s_model, s_rule, task, thr=0.5):
    y = [it["label"][TASKS[task]] for it in items]
    d = lambda idx: (prf([y[i] for i in idx], [s_model[i] >= thr for i in idx])[2] -
                     prf([y[i] for i in idx], [s_rule[i] >= thr for i in idx])[2])
    return d(range(len(y))), boot(d, len(y))


def main():
    allit = load_items()
    if "--lists" in sys.argv:
        write_lists([it for it in allit if not it.get("excluded")])
        return
    print(f"sampled items: {len(allit)}")
    ex = Counter(e for it in allit for e in it.get("excluded", []))
    print("exclusions (an item can have several):", dict(ex))
    items = [it for it in allit if not it.get("excluded")]
    print(f"included: {len(items)}  (risky-looking {sum(it['risky_looking'] for it in items)}, "
          f"benign-looking {sum(not it['risky_looking'] for it in items)})")
    print("by repo:", dict(Counter(it["repo"] for it in items)))
    for st in "ABC":
        sub = [it for it in items if it["stratum"] == st]
        print(f"stratum {st}: n={len(sub)} lost={sum(it['label']['lost'] for it in sub)} "
              f"fails={sum(it['label']['fails'] for it in sub)} half={sum(it['label']['half_applied'] for it in sub)}")
    for t, k in TASKS.items():
        print(f"label {t:5s}: {sum(it['label'][k] for it in items)} / {len(items)}")
    print("tx-mode labels: lost", sum(it["label_tx"]["lost"] for it in items), "fails", sum(it["label_tx"]["fails"] for it in items))
    print("(lost, fails) cells:", dict(Counter((it["label"]["lost"], it["label"]["fails"]) for it in items)))
    mech = Counter(m for it in items if it["label"]["lost"] for m in mechanisms(it))
    print("loss mechanisms (items):", dict(mech))
    print("fail SQLSTATEs (items):", dict(Counter(e.split(":")[0] for it in items for _, e in it["run"]["errors"][:1])))
    print("items with a synthetic-cast failure:", sum(synthetic_cast(it) for it in items))
    toks = sorted(it["state_meta"]["est_tokens"] for it in items)
    print(f"state tokens (est.): median {toks[len(toks) // 2]}, p90 {toks[int(.9 * len(toks))]}, max {toks[-1]}; "
          f"shrink levels {dict(Counter(it['state_meta']['level'] for it in items))}")
    print("\n== rule baselines (no model)")
    for task, rs in RU.RULES.items():
        for nm, fn in rs.items():
            sc = [float(fn(it["statements"])) for it in items]
            print(fmt(evaluate(items, sc, task, f"{task}:{nm}")))
    # sensitivity sets (PREREG §5.4)
    s1 = [it for it in items if not (it["label"]["lost"] and mechanisms(it) == ["partial_copy"])]
    s2 = [it for it in items if not synthetic_cast(it)]
    rk = [it for it in items if it["risky_looking"]]
    sa = [it for it in items if it["stratum"] == "A"]
    for nm, sub in (("stratum A (primary population for lost)", sa), ("S1 no partial-copy-only losses", s1), ("S2 no synthetic-cast failures", s2),
                    ("risky-looking only", rk)):
        print(f"-- {nm}: n={len(sub)}")
        for task, rs in RU.RULES.items():
            for rn, fn in rs.items():
                print("   " + fmt(evaluate(sub, [float(fn(it["statements"])) for it in sub], task, f"{task}:{rn}")))
    # model results, when present
    for model in ("ekbasis", "glm"):
        P = load_preds(model)
        if not P:
            continue
        sub = [it for it in items if it["id"] in P]
        print(f"\n== {model}: {len(sub)} items answered")
        missing = [it for it in items if it["id"] not in P]
        if model == "ekbasis" and len(missing) > 0.02 * len(items):   # PREREG §6: also report them as p = 0.5
            print(f"   {len(missing)} items without an answer (>2%): also scored as 0.5 below")
            P = dict(P, **{it["id"]: {f"p_{t}": 0.5 for t in TASKS} for it in missing})
            sub = items
        for task in TASKS:
            sc = [P[it["id"]].get(f"p_{task}", 0.0) for it in sub]
            print(fmt(evaluate(sub, sc, task, f"{task}:{model}")))
            for nm, fn in RU.RULES[task].items():
                rule_sc = [float(fn(it["statements"])) for it in sub]
                d, ci = paired_f1_diff(sub, sc, rule_sc, task)
                print(f"   F1({model}) - F1({nm}) = {d:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}]")
        # pre-registered verdicts (PREREG §5)
        y = {t: [it["label"][TASKS[t]] for it in sub] for t in TASKS}
        sc = {t: [P[it["id"]].get(f"p_{t}", 0.0) for it in sub] for t in TASKS}
        r3 = [float(RU.r3(it["statements"])) for it in sub]
        f1r = [float(RU.f1(it["statements"])) for it in sub]
        groups = [it["repo"] for it in sub]
        # H1/H2 are judged in stratum A (PREREG §5.1): every loss is there; B and C are negatives a regex already clears
        A_ = [i for i, it in enumerate(sub) if it["stratum"] == "A"]
        yA, sA, rA = [y["lost"][i] for i in A_], [sc["lost"][i] for i in A_], [r3[i] for i in A_]
        a_l = auroc(yA, sA)
        ci_l = boot(lambda idx: auroc([yA[i] for i in idx], [sA[i] for i in idx]), len(A_))
        d2, ci2 = paired_f1_diff([sub[i] for i in A_], sA, rA, "lost")
        groupsA = [groups[i] for i in A_]
        a_f = auroc(y["fails"], sc["fails"])
        ci_f = boot(lambda idx: auroc([y["fails"][i] for i in idx], [sc["fails"][i] for i in idx]), len(sub))
        d3, ci3 = paired_f1_diff(sub, sc["fails"], f1r, "fails")
        cl = cluster_boot(lambda idx: auroc([yA[i] for i in idx], [sA[i] for i in idx]), groupsA)
        print(f"   H1 (stratum A, n={len(A_)}) lost AUROC {a_l:.3f} CI [{ci_l[0]:.3f},{ci_l[1]:.3f}] (repo-cluster CI [{cl[0]:.3f},{cl[1]:.3f}])"
              f" -> {'PASS' if a_l >= 0.85 and ci_l[0] >= 0.80 else 'FAIL'}")
        print(f"   H2 (stratum A) F1(lost) - F1(R3) {d2:+.3f} CI [{ci2[0]:+.3f},{ci2[1]:+.3f}] -> {'PASS' if ci2[0] > 0 else 'FAIL'}")
        print(f"   H3 fails AUROC {a_f:.3f} CI [{ci_f[0]:.3f},{ci_f[1]:.3f}], F1 - F1(rule F1) {d3:+.3f} "
              f"CI [{ci3[0]:+.3f},{ci3[1]:+.3f}] -> {'PASS' if a_f >= 0.80 and ci_f[0] >= 0.70 and ci3[0] > 0 else 'FAIL'}")
        print(f"   H5 lost ECE {ece(y['lost'], sc['lost']):.3f} -> {'PASS' if ece(y['lost'], sc['lost']) <= 0.10 else 'FAIL'}")
        # operating point: Ekbasis at the recall R3 has, and the two-stage guard (R3 alarms confirmed by the model)
        rr = prf(yA, [x >= 0.5 for x in rA])
        thr = max((t for t in sorted(set(sA), reverse=True) if prf(yA, [x >= t for x in sA])[1] >= rr[1]), default=0.0)
        pm = prf(yA, [x >= thr for x in sA])
        print(f"   (A) at R3's recall {rr[1]:.3f}: R3 precision {rr[0]:.3f}, {model} precision {pm[0]:.3f} (threshold {thr:.3f})")
        two = prf(yA, [a >= 0.5 and b >= 0.5 for a, b in zip(rA, sA)])
        print(f"   (A) two-stage R3 AND {model}>=0.5: P {two[0]:.3f} R {two[1]:.3f} F1 {two[2]:.3f}")
        for task in ("lost", "fails"):                         # secondary: the transactional runner's labels
            yt = [it["label_tx"][task] for it in sub]
            st_ = [P[it["id"]].get(f"p_{task}", 0.0) for it in sub]
            pp = prf(yt, [x >= 0.5 for x in st_])
            print(f"   label_tx {task}: pos={sum(yt)} AUROC {auroc(yt, st_):.3f} P {pp[0]:.3f} R {pp[1]:.3f} F1 {pp[2]:.3f}")
        if any("p_f1" in P[it["id"]] for it in sub):        # exploratory: preflight-style aggregate per statement
            agg = []
            for it in sub:
                q = 1.0
                for k in range(1, len(it["statements"]) + 1):
                    q *= 1 - P[it["id"]].get(f"p_f{k}", 0.0)
                agg.append(1 - q)
            print("   " + fmt(evaluate(sub, agg, "fails", "fails:per-statement")))
        for st in "ABC":
            ss = [i for i, it in enumerate(sub) if it["stratum"] == st]
            if ss and 0 < sum(y["lost"][i] for i in ss) < len(ss):
                print(f"   stratum {st}: lost AUROC {auroc([y['lost'][i] for i in ss], [sc['lost'][i] for i in ss]):.3f} n={len(ss)}")
        if model == "ekbasis":
            for nm, ss in (("S1", s1), ("S2", s2)):
                ss = [it for it in ss if it["id"] in P]
                for task in ("lost", "fails"):
                    print("   " + nm + " " + fmt(evaluate(ss, [P[it["id"]].get(f"p_{task}", 0.0) for it in ss], task,
                                                         f"{task}:{model}")))


if __name__ == "__main__":
    main()
