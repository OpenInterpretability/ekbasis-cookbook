"""Recomputes the registered results of the framework evals (v4 and v5) from the released per-item answers.

    python recompute.py      # standard library only; writes recompute_output.txt and compares it with
                             # frozen/fw_eval/results_v4.txt and frozen/fw_eval5/results_v5.txt

The product verdict is recomputed here from the decision in code and the two probabilities (the same rule as
ekbasis.migrations.FileVerdict.kind, thresholds 0.5); the released `product_verdict` field is checked against it. The
rule verdict (R3 OR F1) needs the rendered SQL, which is third-party code and is not released, so it is read from the
`rules_verdict` field. The bootstrap is the frozen one of the first migrations study (../migrations/frozen/analysis.py).
The metric and printing code is copied from frozen/fw_eval/analysis_v4.py and frozen/fw_eval5/analysis_v5.py.
"""
import io
import json
import math
import os
import statistics as st
import sys
from collections import Counter
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "migrations", "frozen"))
import analysis as A  # noqa: E402  (frozen; only boot() is used)

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


def load(name):
    allr = [json.loads(l) for l in open(os.path.join(HERE, name))]
    return [r for r in allr if not r["excluded"]], allr


def product_v4(r):
    d, a = r["decided"], r["answer"]
    if d and d.startswith("cannot_foresee"):
        return True, "cannot_foresee"
    if d == "schema":
        return True, "schema"
    if d == "ok_empty":
        return False, "ok"
    if a is None:
        return True, "cannot_foresee"
    if r["schema_error"]:
        return True, "schema"
    kind = "fails" if a["p_fails"] >= T else "loses" if a["p_lost"] >= T else "ok"
    return kind != "ok", kind


def product_v5(r):
    if r["decided"] == "cannot_foresee_code" or (r["decided"] == "cannot_foresee_render" and r["render_offline_fail"]):
        return False, "code_not_foreseen"
    return product_v4(r)


def rules(r):
    return r["rules_verdict"]["risky"], r["rules_verdict"]["kind"]


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


def cost(rows):
    ans = [r["answer"] for r in rows if r["answer"]]
    tok = [a["input_tokens"] for a in ans if a["input_tokens"] is not None]
    mt = [a["model_ms"] for a in ans if a["model_ms"] is not None]
    return f"cost: {sum(tok):,} input tokens; model median {st.median(mt) / 1000:.2f} s"


def check(allr, fn):
    bad = [r["id"] for r in allr if not r["excluded"]
           and list(fn(r)) != [r["product_verdict"]["risky"], r["product_verdict"]["kind"]]]
    assert not bad, f"product verdict differs from the released field on {len(bad)} items: {bad[:3]}"


def v4():
    rows, allr = load("answers_v4.jsonl")
    check(allr, product_v4)
    print(f"items {len(allr)}, excluded {len(allr) - len(rows)}, analysed {len(rows)}; sent to the model "
          f"{sum(1 for r in rows if not r['decided'])}, answered {sum(1 for r in rows if r['answer'])}")
    print("exclusions:", dict(Counter(e for r in allr for e in r["excluded"])))
    print("decided in code:", dict(Counter(r["decided"] for r in rows)))
    print("truth:", dict(Counter(truth(r)[1] for r in rows)))
    V = {r["id"]: product_v4(r) for r in rows}
    Rv = {r["id"]: rules(r) for r in rows}
    for fw in ("django", "alembic"):
        verdicts([r for r in rows if r["framework"] == fw], V, Rv, f"{fw} (registered, per framework)")
    verdicts(rows, V, Rv, "all (secondary)")
    print("\n== Exploratory")
    metrics([r for r in rows if V[r["id"]][1] != "cannot_foresee"], V, "answered")
    for p_ in sorted({r["project"] for r in rows}):
        metrics([r for r in rows if r["project"] == p_], V, p_[:9])
    print(cost(rows))


def v4_posthoc():
    rows, _ = load("answers_v4.jsonl")
    V = {r["id"]: ((False, "code_not_foreseen") if (r["decided"] or "").startswith("cannot_foresee") else product_v4(r))
         for r in rows}
    for fw in ("django", "alembic"):
        print("POST HOC (code = warning, not blocking):")
        metrics([r for r in rows if r["framework"] == fw], V, fw)


def v5():
    rows, allr = load("answers_v5.jsonl")
    check(allr, product_v5)
    print(f"items {len(allr)}, excluded {len(allr) - len(rows)}, analysed {len(rows)}; sent to the model "
          f"{sum(1 for r in rows if not r['decided'])}, answered {sum(1 for r in rows if r['answer'])}")
    print("exclusions:", dict(Counter(e for r in allr for e in r["excluded"])))
    Vp = {r["id"]: product_v5(r) for r in rows}
    Rv = {r["id"]: rules(r) for r in rows}
    for fw in ("django", "alembic"):
        sub = [r for r in rows if r["framework"] == fw]
        ans = [r for r in sub if Vp[r["id"]][1] != "code_not_foreseen"]
        cnf = [r for r in sub if Vp[r["id"]][1] == "code_not_foreseen"]
        print(f"\n######## {fw}: {len(sub)} migrations, answered {len(ans)}, code not foreseen {len(cnf)}")
        verdicts(ans, Vp, Rv, f"{fw}: registered P1-P4, on the migrations the product answers")
        risky = [r for r in sub if truth(r)[0]]
        caught = [r for r in risky if Vp[r["id"]][0]]
        print(f"  reported: code not foreseen {len(cnf)}/{len(sub)} = {len(cnf) / len(sub):.3f}; truth among them "
              f"{dict(Counter(truth(r)[1] for r in cnf))}")
        print(f"  reported: total recall (code not foreseen counted as not caught) {len(caught)}/{len(risky)} = "
              f"{len(caught) / len(risky):.3f}" if risky else "  no risky migrations")
    print("\n" + cost(rows))


def run(fn):
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn()
    return buf.getvalue()


def main():
    out, report = [], []
    for title, fn, frozen in (("v4", v4, "frozen/fw_eval/results_v4.txt"),
                              ("v4 post hoc", v4_posthoc, "frozen/fw_eval/results_v4_posthoc.txt"),
                              ("v5", v5, "frozen/fw_eval5/results_v5.txt")):
        text = run(fn)
        same = text.strip() == open(os.path.join(HERE, frozen)).read().strip()
        out.append(f"######################## {title}\n{text}")
        report.append(f"{title}: {'identical to' if same else 'DIFFERS from'} {frozen}")
    out.append("######################## check\n" + "\n".join(report) + "\n")
    text = "\n".join(out)
    open(os.path.join(HERE, "recompute_output.txt"), "w").write(text)
    print(text)


if __name__ == "__main__":
    main()
