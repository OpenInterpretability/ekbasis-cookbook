import json, sys
from ekbasis import migrations as M
src, out = sys.argv[1], sys.argv[2]
n = 0
with open(out, "w") as f:
    for l in open(src):
        r = json.loads(l)
        for arm in ("R", "N"):
            a = r[arm]
            if not a["facts"] or a["decided"] or not a["state"]:
                continue
            qs = {"lost": M.Q_LOST, "fails": M.Q_FAILS}
            if a["state"].startswith(M.RULES_AUTO[:60]):
                qs["half"] = M.Q_HALF
            f.write(json.dumps({"id": f"{r['id']}|{arm}", "state": a["state"], "questions": qs}) + "\n"); n += 1
print(n)
