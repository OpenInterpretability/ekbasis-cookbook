"""Framework eval (v4), the registered analysis (PREREG_v4.md section 4). Product verdict and reason: the product's own
code (ekbasis.migrations.FileVerdict; decisions in code as check_bundle makes them). Rules: R3 OR F1 on the rendered
SQL (a migration with no rendered SQL gets "ok" from the rules)."""
import glob
import json
import math
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SP, "pr_study"))
sys.path.insert(0, os.path.join(SP, "mgfw"))
import analysis as A                    # noqa: E402  (study: bootstrap)
import rules as RU                      # noqa: E402
from ekbasis import migrations as M     # noqa: E402

T = 0.5


def wilson(k, n, z=1.96):
    if not n:
        return float("nan"), float("nan")
    p, d = k / n, 1 + z * z / n
    c, h = p + z * z / (2 * n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def binom(b, c):
    n, k = b + c, min(b, c)
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def load():
    items = []
    for p in sorted(glob.glob(os.path.join(HERE, "data", "items", "*.jsonl"))):
        for l in open(p):
            r = json.loads(l)
            r["id"] = f"{r['project']}/{r['path']}"
            items.append(r)
    return [r for r in items if not r.get("excluded")], items


def product(r, pred):
    d = r["product"]["decided"]
    if d and d.startswith("cannot_foresee"):
        return True, "cannot_foresee"
    if d == "schema":
        return True, "schema"
    if d == "ok_empty":
        return False, "ok"
    if pred is None:
        return True, "cannot_foresee"            # no answer: fail closed
    v = M.FileVerdict(r["path"], r["framework"], r["product"]["transaction"], p_lost=pred["p_lost"],
                      p_fail=pred["p_fails"], lost_threshold=T, fail_threshold=T)
    if r["product"].get("schema_error"):
        v.schema_error, v.p_fail = r["product"]["schema_error"], 1.0
    return (bool(v.schema_error) or v.p_lost >= T or v.p_fail >= T), v.kind


def rules(r):
    s = M.split_sql(r["render"].get("sql") or "")
    f, l = RU.f1(s), RU.r3(s)
    return f or l, ("fails" if f else "loses" if l else "ok")


def truth(r):
    lab = r["label"]
    return lab["fails"] or lab["lost"], ("fails" if lab["fails"] else "loses" if lab["lost"] else "ok")


def ok_kind(p, t):
    return {"fails": "fails", "schema": "fails", "loses": "loses"}.get(p) == t


def metrics(rows, V, name, out=print):
    tr = [truth(r) for r in rows]
    acc = sum(V[r["id"]][0] == t[0] for r, t in zip(rows, tr)) / len(rows)
    risky = [r for r, t in zip(rows, tr) if t[0]]
    both = [r for r in risky if V[r["id"]][0]]
    rex = sum(ok_kind(V[r["id"]][1], truth(r)[1]) for r in both) / len(both) if both else float("nan")
    ben = [r for r, t in zip(rows, tr) if not t[0]]
    fa = sum(V[r["id"]][0] for r in ben) / len(ben) if ben else float("nan")
    rec = len(both) / len(risky) if risky else float("nan")
    out(f"  {name:<9} n={len(rows):3d} accuracy {acc:.3f}  recall {rec:.3f} ({len(both)}/{len(risky)})  reason exact "
        f"{rex:.3f} (n={len(both)})  false alarms on benign {fa:.3f} ({sum(V[r['id']][0] for r in ben)}/{len(ben)})")
    return acc, rex, fa, rec, both, ben, risky


def verdicts(rows, V, Rv, label):
    print(f"\n== {label}")
    tr = {r["id"]: truth(r) for r in rows}
    ids = [r["id"] for r in rows]
    acc, rex, fa, rec, both, ben, risky = metrics(rows, V, "product")
    accR, *_ = metrics(rows, Rv, "rules")
    ci = A.boot(lambda idx: sum(V[ids[i]][0] == tr[ids[i]][0] for i in idx) / len(idx), len(ids))
    d = lambda idx: (sum(V[ids[i]][0] == tr[ids[i]][0] for i in idx) - sum(Rv[ids[i]][0] == tr[ids[i]][0] for i in idx)) / len(idx)
    cd = A.boot(d, len(ids))
    print(f"  P1 accuracy {acc:.3f} [{ci[0]:.3f},{ci[1]:.3f}]; minus rules {d(range(len(ids))):+.3f} [{cd[0]:+.3f},{cd[1]:+.3f}]"
          f" -> {'PASS' if acc >= 0.85 and ci[0] >= 0.80 and cd[0] > 0 else 'FAIL'}")
    k = sum(ok_kind(V[r["id"]][1], tr[r["id"]][1]) for r in both)
    w = wilson(k, len(both))
    print(f"  P2 reason exact {k}/{len(both)} [{w[0]:.3f},{w[1]:.3f}] -> {'PASS' if both and k / len(both) >= 0.85 and w[0] >= 0.75 else 'FAIL'}")
    n = sum(V[r["id"]][0] for r in ben)
    w = wilson(n, len(ben))
    b = sum(1 for r in ben if Rv[r["id"]][0] and not V[r["id"]][0])
    c = sum(1 for r in ben if V[r["id"]][0] and not Rv[r["id"]][0])
    faR = sum(Rv[r["id"]][0] for r in ben) / len(ben)
    print(f"  P3 false alarms {n}/{len(ben)} [{w[0]:.3f},{w[1]:.3f}]; rules {faR:.3f}; McNemar p={binom(b, c):.4f} -> "
          f"{'PASS' if n / len(ben) <= 0.20 and w[1] <= 0.30 and n / len(ben) < faR and binom(b, c) < 0.05 else 'FAIL'}")
    w = wilson(len(both), len(risky))
    print(f"  P4 recall {rec:.3f} [{w[0]:.3f},{w[1]:.3f}] -> {'PASS' if rec >= 0.85 else 'FAIL'}")
    cf = sum(V[r["id"]][1] == "cannot_foresee" for r in rows)
    print(f"  C1 cannot foresee: {cf}/{len(rows)} = {cf / len(rows):.3f} (reported, no target)")


def main():
    rows, allr = load()
    pp = os.path.join(HERE, "preds", "v4.jsonl")
    preds = {r["id"]: r for r in map(json.loads, open(pp)) if "error" not in r} if os.path.exists(pp) else {}
    print(f"items {len(allr)}, excluded {len(allr) - len(rows)}, analysed {len(rows)}; sent to the model "
          f"{sum(1 for r in rows if not r['product']['decided'])}, answered {sum(1 for r in rows if r['id'] in preds)}")
    from collections import Counter
    print("exclusions:", dict(Counter(e for r in allr for e in r.get("excluded", []))))
    print("decided in code:", dict(Counter(r["product"]["decided"] for r in rows)))
    print("truth:", dict(Counter(truth(r)[1] for r in rows)))
    V = {r["id"]: product(r, preds.get(r["id"])) for r in rows}
    Rv = {r["id"]: rules(r) for r in rows}
    if not preds:
        print("(no model answers yet: rules only)")
        for fw in ("django", "alembic"):
            sub = [r for r in rows if r["framework"] == fw]
            metrics(sub, Rv, f"rules {fw}")
        return
    for fw in ("django", "alembic"):
        verdicts([r for r in rows if r["framework"] == fw], V, Rv, f"{fw} (registered, per framework)")
    verdicts(rows, V, Rv, "all (secondary)")
    print("\n== Exploratory")
    ans = [r for r in rows if V[r["id"]][1] != "cannot_foresee"]
    metrics(ans, V, "answered", )
    for p_ in sorted({r["project"] for r in rows}):
        metrics([r for r in rows if r["project"] == p_], V, p_[:9])
    tok = [p["usage"]["input_tokens"] for p in preds.values() if p.get("usage")]
    mt = [float(m.group(1)) for p in preds.values() for m in [re.search(r'model;(?:desc="[^"]*";)?dur=([\d.]+)',
                                                                        p.get("server_timing") or "")] if m]
    if tok:
        print(f"cost: {sum(tok):,} input tokens; model median {st.median(mt) / 1000:.2f} s")


if __name__ == "__main__":
    main()
