"""Recomputes the registered criteria P1-P4 of this study from the released answers (standard library only).

    python recompute.py      # writes recompute_output.txt and checks it against frozen/results_v4.txt

The verdict logic is the frozen one (frozen/analysis_v4.py for T1, frozen/score_v4.py for T2), applied to the
reduced answer files: answers_t1.jsonl (the guard's per-file output for each incident, without the state text) and
answers_t2.jsonl (per migration: the frozen label, the code decisions, whether NEW's state is byte-identical to OLD's,
and the model's P(yes) for each arm and regime). The states themselves are not released because they contain
third-party SQL; their sha256 is kept in the answer files.
"""
import io
import json
import os
import sys
from contextlib import redirect_stdout
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = os.path.join(HERE, "frozen")
FAIL = ("fails_data", "fails_schema", "fails_env")
T = 0.5


def load(name):
    return [json.loads(l) for l in open(os.path.join(HERE, name))]


def mcnemar(b, c):
    n = b + c
    return sum(comb(n, k) for k in range(b, n + 1)) / 2 ** n if n else 1.0


# ---- T1 (frozen/analysis_v4.py)
def caught(up, f):
    if not f:
        return "missed", None
    k = f["kind"]
    if k == "cannot_foresee":
        return "cannot_foresee", k
    if k == "ok":
        return "missed", k
    want = ("schema", "fails") if up in FAIL else ("loses",)
    return ("caught" if k in want else "caught_wrong_why"), k


def t1(inc, sets):
    out = {}
    for arm in ("N", "R"):
        rows = []
        for c in [c for c in inc if c["set"] in sets]:
            r = {}
            for v in ("old", "new"):
                d = c[v]
                f = next((x for x in d[arm]["files"] if x["path"] == c["path"]), None)
                r[v] = caught(c["upstream"], f) + ((f or {}).get("p_lost"), (f or {}).get("p_fail"), d.get("error"))
            rows.append((c, r))
        gains = [c["id"] for c, r in rows if r["new"][0] == "caught" and r["old"][0] != "caught"]
        losses = [c["id"] for c, r in rows if r["old"][0] == "caught" and r["new"][0] != "caught"]
        co, cn = (sum(r[v][0] == "caught" for _, r in rows) for v in ("old", "new"))
        out[arm] = (rows, co, cn, gains, losses)
    return out


# ---- T2 (frozen/score_v4.py)
def verdict(st, ans):
    d = st["decided"]
    if d in ("schema", "fails_code"):
        return True, "fails"
    if d in ("cannot_foresee", "missing"):
        return True, "cannot_foresee"
    if d == "ok_empty":
        return False, None
    if ans is None or "error" in ans:
        return None, None
    pf, pl = ans.get("p_fails", 0), ans.get("p_lost", 0)
    if st.get("schema_error_autocommit"):
        pf = 1.0
    if pf >= T:
        return True, "fails"
    if pl >= T:
        return True, "loses"
    return False, None


def t2(items, arm):
    rows = []
    for it in items:
        lp = it["label_product"]
        risky = bool(lp["lost"] or lp["fails"])
        why = "fails" if lp["fails"] else ("loses" if risky else None)
        a = it[arm]
        same = a["same_state"]
        vo = verdict(a["old"], a["old"]["answer"])
        vn = verdict(a["new"], a["old"]["answer"] if same else a["new"]["answer"])
        rows.append((it["id"], risky, why, vo, vn, same))

    def stats(k):
        ben = [r for r in rows if not r[1] and r[k][0] is not None]
        rk = [r for r in rows if r[1] and r[k][0] is not None]
        fa = sum(r[k][0] for r in ben)
        rec = sum(r[k][0] for r in rk)
        exact = sum(1 for r in rk if r[k][0] and r[k][1] == r[2])
        acc = sum(1 for r in rows if r[k][0] is not None and r[k][0] == r[1])
        n = sum(1 for r in rows if r[k][0] is not None)
        return fa, len(ben), rec, len(rk), exact, acc, n

    res = {}
    for k, name in ((3, "OLD"), (4, "NEW")):
        fa, nb, rec, nr, ex, acc, n = res[name] = stats(k)
        print(f"{name}: false alarms {fa}/{nb} = {fa / max(nb, 1):.3f}; recall {rec}/{nr} = {rec / max(nr, 1):.3f}; "
              f"reason exact {ex}/{max(rec, 1)}; accuracy {acc}/{n}")
    unanswered = [r[0] for r in rows if r[3][0] is None or r[4][0] is None]
    print("unanswered", len(unanswered), unanswered[:5], "| changed items", sum(1 for r in rows if not r[5]))
    ben_up = [r[0] for r in rows if not r[1] and r[4][0] and not r[3][0]]
    ben_down = [r[0] for r in rows if not r[1] and r[3][0] and not r[4][0]]
    rk_up = [r[0] for r in rows if r[1] and r[4][0] and not r[3][0]]
    rk_down = [r[0] for r in rows if r[1] and r[3][0] and not r[4][0]]
    print(f"benign: new alarms {len(ben_up)}, alarms removed {len(ben_down)} | risky: newly flagged {len(rk_up)}, "
          f"no longer flagged {len(rk_down)}")
    for lbl, xs in (("benign new alarm", ben_up), ("benign alarm removed", ben_down), ("risky newly flagged", rk_up),
                    ("risky lost", rk_down)):
        for x in xs:
            print(f"  {lbl}: {x}")
    return res


def main():
    inc, items = load("answers_t1.jsonl"), load("answers_t2.jsonl")
    print("== T1 (primary set, n=9) and T1+T1b (secondary, n=10)")
    p1 = None
    for sets, label in ((("T1",), "T1"), (("T1", "T1b"), "T1+T1b")):
        res = t1(inc, sets)
        for arm in ("N", "R"):
            rows, co, cn, g, l = res[arm]
            p = mcnemar(len(g), len(l))
            tag = "P1 (primary)" if (label == "T1" and arm == "N") else "secondary"
            if tag.startswith("P1"):
                p1 = (cn - co, p, len(rows))
            print(f"{label} regime {arm} [{tag}]: caught OLD {co}/{len(rows)}, NEW {cn}/{len(rows)}; net {cn - co:+d}; "
                  f"gains {g}; losses {l}; McNemar one-sided p={p:.3f}")
            if label == "T1+T1b":
                for c, r in rows:
                    fmt = lambda x: (f"{x[0]}({x[1]}; L{x[2] if x[2] is None else round(x[2], 2)} "
                                     f"F{x[3] if x[3] is None else round(x[3], 2)}){' ERR ' + x[4] if x[4] else ''}")
                    print(f"   {c['id']:<32} {c['upstream']:<12} OLD {fmt(r['old'])}  NEW {fmt(r['new'])}")
    print()
    print("== T2 (v3 184; labels_v3)")
    t2r = {}
    for arm in ("R", "N"):
        print(f"-- regime {arm}")
        t2r[arm] = t2(items, arm)
        print()
    print()
    print("== Registered decision (recomputed)")
    net, p, n = p1
    print(f"P1 T1 regime N: NEW - OLD = {net} (p={p:.3f}, n={n}) -> {'PASS' if net >= 3 and p <= 0.10 else 'FAIL'}")
    fa, nb = t2r["R"]["NEW"][:2]
    print(f"P2 T2 regime R: NEW false alarms {fa}/{nb} -> {'PASS' if fa <= 23 else 'FAIL'}")
    d = t2r["N"]["NEW"][0] - t2r["N"]["OLD"][0]
    print(f"P3 T2 regime N: NEW - OLD false alarms = {d:+d} items -> {'PASS' if d <= 3 else 'FAIL'}")
    rn, ro = t2r["R"]["NEW"][2], t2r["R"]["OLD"][2]
    print(f"P4 T2 regime R: recall NEW {rn}/{t2r['R']['NEW'][3]} vs OLD {ro}/{t2r['R']['OLD'][3]} -> "
          f"{'PASS' if rn >= ro - 2 else 'FAIL'}")


if __name__ == "__main__":
    buf = io.StringIO()
    with redirect_stdout(buf):
        main()
    out = buf.getvalue()
    open(os.path.join(HERE, "recompute_output.txt"), "w").write(out)
    print(out, end="")
    frozen = open(os.path.join(FROZEN, "results_v4.txt")).read().split("== Registered decision")[0].rstrip()
    mine = out.split("== Registered decision")[0].rstrip()
    print("\nT1 and T2 sections identical to frozen/results_v4.txt:", frozen == mine)
    sys.exit(0 if frozen == mine else 1)
