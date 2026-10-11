"""Dev check: R2 on the v1 pilot's 75 scenarios (v1 facts and v1 label definitions; development material only)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rule2
V1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vert_k8s")
labs = {**json.load(open(f"{V1}/labels_dev.json")), **json.load(open(f"{V1}/labels_test.json"))}
tot = {k: [0, 0, 0, 0] for k in ("lost", "down", "exposed")}
for i in sorted(labs, key=int):
    fx = json.load(open(f"{V1}/runs/s{i}/facts.json"))
    try:
        r = rule2.rule2(fx)
    except Exception as e:
        print(f"s{i} CRASH {type(e).__name__}: {e}"); continue
    bad = []
    for k in tot:
        g, p = labs[i][k], r[k]
        tot[k][(2 if g else 0) + (1 if p else 0)] += 1
        if g != p:
            bad.append(f"{k} gold {int(g)} r2 {int(p)}")
    if bad:
        print(f"s{i}: {'; '.join(bad)} | {r['why']}")
for k, (tn, fp, fn, tp) in tot.items():
    print(k, f"tp {tp} fp {fp} fn {fn} tn {tn}")
