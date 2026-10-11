"""Dev only: R2/R1 against the dev labels and a state build smoke test (no Ekbasis call). usage: check_dev.py [ids]"""
import json, os, sys
import guard as G, rule2 as R2, scenarios as SC
ROOT = os.path.dirname(os.path.abspath(__file__))
ids = [int(x) for x in sys.argv[1:]] or [s["id"] for s in SC.S if s["split"] == "dev"]
for i in ids:
    d = os.path.join(ROOT, "runs", f"s{i}")
    try:
        res = json.load(open(f"{d}/result.json")); fx = json.load(open(f"{d}/facts.json"))
    except FileNotFoundError:
        print(f"s{i} not run"); continue
    if not res.get("labels"):
        print(f"s{i} ERROR {res.get('error','')[:200]}"); continue
    st = G.build_state(fx, res["commands"])
    r2, r1, l = R2.rule2(fx), G.rule(fx), res["labels"]
    cells = " ".join(f"{k[:4]} {l[k]!s:5}/{int(r2[k])}/{int(r1[k])}{'' if l[k] is None or bool(r2[k]) == l[k] else '*'}"
                     for k in ("lost", "down", "exposed"))
    print(f"s{i:<3} {cells} fail {int(l['failed'])}/{int(r2['fails'])} gap {res.get('max_gap_s')} "
          f"new {res.get('newly_accessible')} state {len(st)}ch | {res['title'][:60]}")
    if any(l[k] is not None and bool(r2[k]) != l[k] for k in ("lost", "down", "exposed")):
        print("      why:", r2["why"])
