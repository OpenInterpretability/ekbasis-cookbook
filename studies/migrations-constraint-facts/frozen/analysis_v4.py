"""v4: the registered criteria (PREREG_v4 section 5) from the frozen inputs and the answers.

    python3 analysis_v4.py
"""
import json, os, subprocess, sys
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__))
FAIL = ("fails_data", "fails_schema", "fails_env")


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


def mcnemar(b, c):
    n = b + c
    return sum(comb(n, k) for k in range(b, n + 1)) / 2 ** n if n else 1.0


def t1(sets):
    inc = [json.loads(l) for l in open(os.path.join(HERE, "incidents_v4.jsonl")) if json.loads(l)["set"] in sets]
    out = {}
    for arm in ("N", "R"):
        rows = []
        for c in inc:
            r = {}
            for v in ("old", "new"):
                p = os.path.join(HERE, "results", f"t1_{v}", c["id"] + ".json")
                d = json.load(open(p)) if os.path.exists(p) else {}
                f = next((x for x in d.get(arm, {}).get("files", []) if x["path"] == c["path"]), None)
                r[v] = caught(c["upstream"], f) + ((f or {}).get("p_lost"), (f or {}).get("p_fail"), d.get("error"))
            rows.append((c, r))
        gains = [c["id"] for c, r in rows if r["new"][0] == "caught" and r["old"][0] != "caught"]
        losses = [c["id"] for c, r in rows if r["old"][0] == "caught" and r["new"][0] != "caught"]
        co, cn = (sum(r[v][0] == "caught" for _, r in rows) for v in ("old", "new"))
        out[arm] = (rows, co, cn, gains, losses)
    return out


def main():
    print("== T1 (primary set, n=9) and T1+T1b (secondary, n=10)")
    for sets, label in ((("T1",), "T1"), (("T1", "T1b"), "T1+T1b")):
        res = t1(sets)
        for arm in ("N", "R"):
            rows, co, cn, g, l = res[arm]
            p = mcnemar(len(g), len(l))
            tag = "P1 (primary)" if (label == "T1" and arm == "N") else "secondary"
            print(f"{label} regime {arm} [{tag}]: caught OLD {co}/{len(rows)}, NEW {cn}/{len(rows)}; net {cn - co:+d}; "
                  f"gains {g}; losses {l}; McNemar one-sided p={p:.3f}")
            if label == "T1+T1b":
                for c, r in rows:
                    fmt = lambda x: f"{x[0]}({x[1]}; L{x[2] if x[2] is None else round(x[2], 2)} F{x[3] if x[3] is None else round(x[3], 2)}){' ERR ' + x[4] if x[4] else ''}"
                    print(f"   {c['id']:<32} {c['upstream']:<12} OLD {fmt(r['old'])}  NEW {fmt(r['new'])}")
        n1 = len(t1(sets)["N"][0])
    print()
    print("== T2 (v3 184; labels_v3)")
    for arm in ("R", "N"):
        print(f"-- regime {arm}")
        r = subprocess.run([sys.executable, os.path.join(HERE, "score_v4.py"), f"{HERE}/st/t2_old.{arm}.jsonl",
                            f"{HERE}/st/t2_new.{arm}.jsonl", f"{HERE}/ans/t2_old.{arm}.jsonl",
                            f"{HERE}/ans/t2_new.{arm}.jsonl", f"{HERE}/data/labels_v3.jsonl"], capture_output=True, text=True)
        print(r.stdout + r.stderr)


if __name__ == "__main__":
    main()
