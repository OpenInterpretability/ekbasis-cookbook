"""Per-client calibration study (PREREG.md). Uses only probabilities already recorded by earlier studies.

python3 analysis.py dev    -> dev_results.json + selection.json  (dev clients only)
python3 analysis.py test   -> test_results.json                  (needs selection.json; test + secondary clients)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
COOK = os.environ.get("EKBASIS_COOKBOOK_STUDIES", os.path.join(os.path.dirname(__file__), ".."))
SCR = os.path.dirname(HERE)
SALT = "ekbasis-percliente-2026-10-11:"
KS = [5, 10, 20, 50]
K_PRIMARY = 20
MIN_TEST = 10
SEEDS = 20
NOISE_FRAC = 0.20
BOOT = 10000
K0_GRID = [10, 30, 100]
S_GRID = [0.25, 0.5, 1.0, 2.0]
EPS = 1e-6
MIG_REPOS = ["calcom", "cratesio", "documenso", "formbricks", "hoppscotch", "kratos", "langfuse", "lemmy",
             "mattermost", "triggerdev", "umami", "vaultwarden"]
TS_CLIENTS = ["agentharm", "asb", "agentdojo/workspace", "agentdojo/travel", "agentdojo/slack", "agentdojo/banking"]


def h(name):
    return hashlib.sha256((SALT + name).encode()).hexdigest()


DEV_MIG = set(sorted(MIG_REPOS, key=h)[:4])
DEV_TS = set(sorted(TS_CLIENTS, key=h)[:2])


# ---------------------------------------------------------------- data

def client(family, name, unit, task, order, items):
    return {"family": family, "name": f"{family}:{name}:{task}", "unit": unit, "task": task, "order": order,
            "items": items}


def load_m1():
    by = defaultdict(list)
    for l in open(f"{COOK}/migrations/answers.jsonl"):
        r = json.loads(l)
        by[r["repo"]].append(r)
    out = []
    for repo, rows in by.items():
        rows.sort(key=lambda r: r["id"])
        for task in ("lost", "fails"):
            items = [(r["ekbasis"][task], int(r["label"][task]), r["id"]) for r in rows]
            out.append(client("M1", repo, "mig:" + repo, task, "temporal", items))
    return out


def load_m3():
    by = defaultdict(list)
    for l in open(f"{COOK}/migrations/v3/answers_v3.jsonl"):
        r = json.loads(l)
        by[r["repo"]].append(r)
    out = []
    for repo, rows in by.items():
        rows.sort(key=lambda r: r["id"])
        for task in ("lost", "fails"):
            items = [(r["ekbasis"][task], int(r["label_product"][task]), r["id"]) for r in rows
                     if r["ekbasis"] and r["ekbasis"].get(task) is not None]
            out.append(client("M3", repo, "mig:" + repo, task, "temporal", items))
    return out


def load_m5():
    lab = {}
    published = not os.path.exists(f"{SCR}/fw_eval5/preds/v5.jsonl")   # run from the cookbook: the published files
    labels = (f"{COOK}/migrations-frameworks/frozen/fw_eval5/data/labels_v5.jsonl" if published
              else f"{SCR}/fw_eval5/data/labels_v5.jsonl")
    for l in open(labels):
        r = json.loads(l)
        lab[r["id"]] = r
    by = defaultdict(list)
    preds = f"{COOK}/migrations-frameworks/answers_v5.jsonl" if published else f"{SCR}/fw_eval5/preds/v5.jsonl"
    for l in open(preds):
        r = json.loads(l)
        if published:
            r = {"id": r["id"], **(r.get("answer") or {})}
        if r.get("p_lost") is None or r["id"] not in lab:
            continue
        by[r["id"].split("/")[0]].append((r, lab[r["id"]]))
    out = []
    for proj, rows in by.items():
        rows.sort(key=lambda x: x[0]["id"])
        for task, pk in (("lost", "p_lost"), ("fails", "p_fails")):
            items = [(p[pk], int(l["label"][task]), p["id"]) for p, l in rows]
            out.append(client("M5", proj, "fw:" + proj, task, "random", items))
    return out


def load_ts():
    raw = os.path.join(HERE, "tsbench_raw")
    files = {"benign_steps.json": "agentharm-traj/benign_steps.json", "harmful_steps.json": "agentharm-traj/harmful_steps.json",
             "DPI_attack_success.json": "asb-traj/test/DPI_attack_success.json",
             "OPI_attack_success.json": "asb-traj/test/OPI_attack_success.json",
             "atttack_failure.json": "asb-traj/test/atttack_failure.json",
             "workspace.json": "agentdojo-traj/workspace.json", "travel.json": "agentdojo-traj/travel.json",
             "slack.json": "agentdojo-traj/slack.json", "banking.json": "agentdojo-traj/banking.json"}
    cluster = {}
    for base, rel in files.items():
        for i, rec in enumerate(json.load(open(os.path.join(raw, rel)))):
            cluster[f"{base}#{i}"] = f"{rel}:{rec['id-interaction']}"
    by = defaultdict(list)
    for l in open(f"{COOK}/tsbench/answers.jsonl"):
        r = json.loads(l)
        if r.get("p_unsafe") is None:
            continue
        subset, rest = r["id"].split("/", 1)
        name = subset if subset in ("agentharm", "asb") else f"agentdojo/{rest.split('.json')[0]}"
        by[name].append((r["p_unsafe"], 1 if r["label"] >= 0.5 else 0, cluster[rest]))
    return [client("TS", n, "ts:" + n, "unsafe", "random", by[n]) for n in TS_CLIENTS]


# ---------------------------------------------------------------- methods (decision: predict 1 iff score >= 0.5)

def logit(p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sig(z):
    return 1 / (1 + np.exp(-z))


def candidates(z):
    u = np.unique(z)
    mids = (u[1:] + u[:-1]) / 2 if len(u) > 1 else np.array([])
    return np.concatenate([[0.0, u[0] - 1e-3, u[-1] + 1e-3], mids])


def fit_threshold(z, y, floor=False):
    """Logit threshold maximising training accuracy; ties -> nearest 0 (the global threshold).
    floor=True: training recall may not fall below the global threshold's; with no positive, t may not rise above 0."""
    c = candidates(z)
    pos = y.sum()
    rec0 = ((z >= 0) & (y == 1)).sum()
    best = None
    for t in c:
        pred = z >= t
        if floor:
            if pos == 0 and t > 0:
                continue
            if pos > 0 and (pred & (y == 1)).sum() < rec0:
                continue
        acc = (pred == y).mean()
        key = (acc, -abs(t))
        if best is None or key > best[0]:
            best = (key, t)
    return best[1]


def fit_platt(z, y, s, slope=True):
    """MAP of q = sig(a z + b) with a ~ N(1, (s/2)^2) (if slope) and b ~ N(0, s^2). Newton's method."""
    a, b = 1.0, 0.0
    va, vb = (s / 2) ** 2, s ** 2
    for _ in range(50):
        q = sig(a * z + b)
        g_b = (y - q).sum() - b / vb
        h_bb = -(q * (1 - q)).sum() - 1 / vb
        if not slope:
            step = g_b / h_bb
            b -= step
            if abs(step) < 1e-9:
                break
            continue
        g_a = ((y - q) * z).sum() - (a - 1) / va
        w = q * (1 - q)
        h_aa = -(w * z * z).sum() - 1 / va
        h_ab = -(w * z).sum()
        H = np.array([[h_aa, h_ab], [h_ab, h_bb]])
        step = np.linalg.solve(H, np.array([g_a, g_b]))
        a, b = a - step[0], b - step[1]
        if np.abs(step).max() < 1e-9:
            break
    return a, b


def apply_methods(ztr, ytr, zte, hp):
    """Returns {method: (decision array, probability array)} for the test items."""
    out = {"G": (zte >= 0, sig(zte))}
    tA = fit_threshold(ztr, ytr)
    out["A"] = (zte >= tA, sig(zte))
    tR = fit_threshold(ztr, ytr, floor=True)
    out["AR"] = (zte >= tR, sig(zte))
    k = len(ytr)
    for k0 in hp.get("K0", K0_GRID):
        tc = k / (k + k0) * tA
        out[f"C{k0}"] = (zte >= tc, sig(zte))
    for s in hp.get("S", S_GRID):
        _, b = fit_platt(ztr, ytr, s, slope=False)
        q = sig(zte + b)
        out[f"B0_{s}"] = (q >= 0.5, q)
        a, b = fit_platt(ztr, ytr, s)
        q = sig(a * zte + b)
        out[f"B_{s}"] = (q >= 0.5, q)
    return out


# ---------------------------------------------------------------- splits and noise

def realisations(c, k):
    """Yields (train idx, test idx). Temporal: one split by time. Random: SEEDS shuffles of whole clusters."""
    items = c["items"]
    n = len(items)
    if c["order"] == "temporal":
        if n - k >= MIN_TEST:
            yield 0, list(range(k)), list(range(k, n))
        return
    clusters = defaultdict(list)
    for i, it in enumerate(items):
        clusters[it[2]].append(i)
    keys = sorted(clusters)
    for seed in range(SEEDS):
        rng = random.Random(f"{c['name']}|{k}|{seed}")
        order = keys[:]
        rng.shuffle(order)
        tr, touched = [], 0
        for key in order:
            if len(tr) >= k:
                break
            tr.extend(clusters[key][: k - len(tr)])
            touched += 1
        te = [i for key in order[touched:] for i in clusters[key]]
        if len(tr) == k and len(te) >= MIN_TEST:
            yield seed, tr, te


def corrupt(y, noise, rng):
    y = y.copy()
    m = int(round(NOISE_FRAC * len(y)))
    if noise == "flip":
        for i in rng.sample(range(len(y)), m):
            y[i] = 1 - y[i]
    elif noise == "silence":  # an adversary marks real positives as "false alarm"
        pos = [i for i in range(len(y)) if y[i] == 1]
        for i in rng.sample(pos, min(m, len(pos))):
            y[i] = 0
    return y


# ---------------------------------------------------------------- metrics

def ece(y, q, bins=10):
    tot, err = len(y), 0.0
    idx = np.minimum((q * bins).astype(int), bins - 1)
    for b in range(bins):
        m = idx == b
        if m.any():
            err += m.sum() / tot * abs(y[m].mean() - q[m].mean())
    return err


def stats(y, d, q):
    tp = int((d & (y == 1)).sum()); fp = int((d & (y == 0)).sum())
    fn = int((~d & (y == 1)).sum()); tn = int((~d & (y == 0)).sum())
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 1.0
    return {"acc": (tp + tn) / len(y), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "f1": f1,
            "brier": float(((q - y) ** 2).mean()), "ece": ece(y, q)}


def evaluate(clients, hp, noises=("none",), ks=KS):
    """res[noise][k][client] = {method: mean stats over realisations}"""
    res = {}
    for noise in noises:
        res[noise] = {}
        for k in ks:
            res[noise][k] = {}
            for c in clients:
                p = np.array([it[0] for it in c["items"]], float)
                y = np.array([it[1] for it in c["items"]], int)
                z = logit(p)
                acc = defaultdict(lambda: defaultdict(float))
                nr = 0
                for seed, tr, te in realisations(c, k):
                    rng = random.Random(f"noise|{noise}|{c['name']}|{k}|{seed}")
                    reps = SEEDS if (noise != "none" and c["order"] == "temporal") else 1
                    for r in range(reps):
                        ytr = corrupt(y[tr], noise, random.Random(f"{rng.random()}|{r}"))
                        meth = apply_methods(z[tr], ytr, z[te], hp)
                        for m, (d, q) in meth.items():
                            for key, v in stats(y[te], d, q).items():
                                acc[m][key] += v
                        nr += 1
                if nr:
                    res[noise][k][c["name"]] = {m: {key: v / nr for key, v in d.items()} for m, d in acc.items()}
                    res[noise][k][c["name"]]["_n_test"] = len(c["items"]) - k
                    res[noise][k][c["name"]]["_unit"] = c["unit"]
    return res


def deltas(rk, method, key):
    """Per-client delta of `key` (method minus G), and the units."""
    names = [n for n in rk]
    return {n: rk[n][method][key] - rk[n]["G"][key] for n in names}, {n: rk[n]["_unit"] for n in names}


def macro_ci(d, units, seed=0):
    names = list(d)
    if not names:
        return None
    by = defaultdict(list)
    for n in names:
        by[units[n]].append(d[n])
    U = list(by)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(BOOT):
        pick = rng.integers(0, len(U), len(U))
        xs = [x for i in pick for x in by[U[i]]]
        vals.append(np.mean(xs))
    return float(np.mean(list(d.values()))), float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def pooled_recall(rk, method):
    tp = sum(rk[n][method]["tp"] for n in rk); fn = sum(rk[n][method]["fn"] for n in rk)
    fp = sum(rk[n][method]["fp"] for n in rk); tn = sum(rk[n][method]["tn"] for n in rk)
    return (tp / (tp + fn) if tp + fn else float("nan")), (fp / (fp + tn) if fp + tn else float("nan"))


def summary(res, methods, label, out):
    for noise in res:
        for k in res[noise]:
            rk = res[noise][k]
            if not rk:
                continue
            for m in methods:
                row = {"set": label, "noise": noise, "k": k, "method": m, "clients": len(rk)}
                for key in ("acc", "f1", "brier", "ece"):
                    d, u = deltas(rk, m, key)
                    row["d_" + key] = macro_ci(d, u)
                rec, far = pooled_recall(rk, m)
                rec0, far0 = pooled_recall(rk, "G")
                row["recall"], row["recall_G"], row["far"], row["far_G"] = rec, rec0, far, far0
                out.append(row)


def fmt(ci):
    return "   n/a" if ci is None else f"{ci[0]:+.4f} [{ci[1]:+.4f}, {ci[2]:+.4f}]"


def show(rows, keys=("acc", "brier")):
    for r in rows:
        print(f"{r['set']:5s} {r['noise']:7s} k={r['k']:<3d} {r['method']:7s} n={r['clients']:<3d} "
              + " ".join(f"d{k} {fmt(r['d_' + k])}" for k in keys)
              + f"  recall {r['recall']:.3f} (G {r['recall_G']:.3f}) FAR {r['far']:.3f} (G {r['far_G']:.3f})")


# ---------------------------------------------------------------- phases

def all_clients():
    return load_m1() + load_m3() + load_m5() + load_ts()


def split(cs):
    dev = [c for c in cs if (c["family"] == "M1" and c["unit"][4:] in DEV_MIG) or
           (c["family"] == "TS" and c["unit"][3:] in DEV_TS)]
    test = [c for c in cs if (c["family"] == "M1" and c["unit"][4:] not in DEV_MIG) or
            (c["family"] == "TS" and c["unit"][3:] not in DEV_TS)]
    m3 = [c for c in cs if c["family"] == "M3" and c["unit"][4:] not in DEV_MIG]
    m5 = [c for c in cs if c["family"] == "M5"]
    return dev, test, m3, m5


def phase_dev():
    dev, *_ = split(all_clients())
    print("dev clients:", sorted({c["unit"] for c in dev}))
    res = evaluate(dev, {}, noises=("none",))
    rk = res["none"][K_PRIMARY]
    score = {}
    for m in next(iter(rk.values())):
        if m.startswith("_") or m == "G":
            continue
        d, _ = deltas(rk, m, "acc")
        db, _ = deltas(rk, m, "brier")
        score[m] = (float(np.mean(list(d.values()))), float(np.mean(list(db.values()))))
    k0 = max(K0_GRID, key=lambda v: score[f"C{v}"][0])
    s0 = max(S_GRID, key=lambda v: score[f"B0_{v}"][0])
    s1 = max(S_GRID, key=lambda v: score[f"B_{v}"][0])
    fam = {"A": "A", "AR": "AR", "C": f"C{k0}", "B0": f"B0_{s0}", "B": f"B_{s1}"}
    primary = max(fam.values(), key=lambda m: score[m][0])
    sb0 = max(S_GRID, key=lambda v: -score[f"B0_{v}"][1])
    sb1 = max(S_GRID, key=lambda v: -score[f"B_{v}"][1])
    cal = min([f"B0_{sb0}", f"B_{sb1}"], key=lambda m: score[m][1])
    sel = {"k0": k0, "s_B0": s0, "s_B": s1, "families": fam, "primary_decision": primary,
           "s_B0_brier": sb0, "s_B_brier": sb1, "primary_calibration": cal, "dev_scores_k20": score}
    json.dump(sel, open(os.path.join(HERE, "selection.json"), "w"), indent=1)
    rows = []
    summary(res, sorted(score) + ["G"], "dev", rows)
    json.dump(rows, open(os.path.join(HERE, "dev_results.json"), "w"), indent=1)
    show([r for r in rows if r["method"] in list(fam.values()) + [cal]])
    print(json.dumps({k: v for k, v in sel.items() if k != "dev_scores_k20"}, indent=1))


def phase_test():
    sel = json.load(open(os.path.join(HERE, "selection.json")))
    _, test, m3, m5 = split(all_clients())
    print("test clients:", sorted({c["unit"] for c in test}))
    pd, pc = sel["primary_decision"], sel["primary_calibration"]
    hp = {"K0": [sel["k0"]], "S": sorted({sel["s_B0"], sel["s_B"], sel["s_B0_brier"], sel["s_B_brier"]})}
    methods = ["A", "AR", f"C{sel['k0']}", f"B0_{sel['s_B0']}", f"B_{sel['s_B']}", pc]
    methods = list(dict.fromkeys(methods))
    rows = []
    for label, cs, noises in (("test", test, ("none", "flip", "silence")), ("M3", m3, ("none",)),
                              ("M5", m5, ("none", "flip", "silence"))):
        res = evaluate(cs, hp, noises=noises)
        summary(res, methods, label, rows)
        if label == "test":
            per = {k: {n: {m: res["none"][k][n][m] for m in methods + ["G"]} | {"n_test": res["none"][k][n]["_n_test"]}
                       for n in res["none"][k]} for k in KS}
            json.dump(per, open(os.path.join(HERE, "test_per_client.json"), "w"), indent=1)
    json.dump(rows, open(os.path.join(HERE, "test_results.json"), "w"), indent=1)
    show(rows)

    print("\n== pre-registered verdicts (test set, k=20)")
    get = lambda noise, m: next(r for r in rows if r["set"] == "test" and r["noise"] == noise and r["k"] == K_PRIMARY
                                and r["method"] == m)
    r = get("none", pd)
    h1 = r["d_acc"][1] > 0 and (r["recall"] - r["recall_G"]) >= -0.05
    print(f"H1 decision {pd}: dacc {fmt(r['d_acc'])}, recall {r['recall']:.3f} vs {r['recall_G']:.3f} -> "
          f"{'PASS' if h1 else 'FAIL'}")
    rc = get("none", pc)
    h2 = rc["d_brier"][2] < 0
    print(f"H2 calibration {pc}: dBrier {fmt(rc['d_brier'])} -> {'PASS' if h2 else 'FAIL'}")
    for m, hname in ((pd, "decision"), (pc, "calibration")):
        ok = True
        for noise in ("flip", "silence"):
            rn = get(noise, m)
            this = rn["d_acc"][0] >= -0.01 and (rn["recall"] - rn["recall_G"]) >= -0.05
            if hname == "calibration":
                this = this and rn["d_brier"][0] <= 0.0
            ok &= this
            print(f"S  {hname} {m} {noise}: dacc {fmt(rn['d_acc'])} dBrier {fmt(rn['d_brier'])} "
                  f"recall {rn['recall']:.3f} vs {rn['recall_G']:.3f} -> {'ok' if this else 'FAIL'}")
        print(f"S  {hname}: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    {"dev": phase_dev, "test": phase_test}[sys.argv[1]]()
