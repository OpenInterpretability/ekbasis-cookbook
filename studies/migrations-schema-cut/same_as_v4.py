"""O estado OLD montado do catálogo reconstruído é byte a byte o do v4 (mesmo schema, mesmo produto)?"""
import glob, json, os, sys
sys.path.insert(0, "ekbasis")
from ekbasis import migrations as M
mine, v4dir = sys.argv[1:3]
same = diff = miss = 0
for p in glob.glob(mine + "/*.jsonl"):
    v4 = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(v4dir, os.path.basename(p)))}
    for l in open(p):
        r = json.loads(l); x = r.get("raw") or {}; y = (v4.get(r["id"]) or {}).get("raw") or {}
        if x.get("decided") != y.get("decided"):
            diff += 1; print("decided differs", r["id"], x.get("decided"), y.get("decided")); continue
        if "catalog" not in x:
            same += 1; continue
        if "catalog" not in y:
            miss += 1; continue
        a = M._named_state(x["catalog"], x["statements"], y["stats"], x["tool"], x["transaction"], [])[0]
        b = M._named_state(y["catalog"], y["statements"], y["stats"], y["tool"], y["transaction"], [])[0]
        if a == b: same += 1
        else: diff += 1; print("state differs", r["id"])
print(f"same {same} differ {diff} missing {miss}")
