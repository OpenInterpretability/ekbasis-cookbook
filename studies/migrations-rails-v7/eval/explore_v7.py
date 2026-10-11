"""Exploratory (not registered): v7 answers without the schema-only rule, per project, and the false alarms."""
import json, os, sys
from collections import Counter
import analysis_v7 as A
V4, V5 = A.V4, A.V5
rows, allr = V4.load()
preds = {r["id"]: r for r in map(json.loads, open(os.path.join(A.HERE, "preds", "v7.jsonl"))) if "error" not in r}
for name, f in (("without the rule", lambda r: V5.product(r, preds.get(r["id"]))), ("v7", lambda r: A.product(r, preds.get(r["id"])))):
    V = {r["id"]: f(r) for r in rows}
    ans = [r for r in rows if V[r["id"]][1] != "code_not_foreseen"]
    for proj in (None, "consuldemocracy", "openproject", "redmine"):
        s = [r for r in ans if proj in (None, r["project"])]
        risky = [r for r in s if V4.truth(r)[0]]
        caught = [r for r in risky if V[r["id"]][0]]
        ok = [r for r in s if not V4.truth(r)[0]]
        print(f"{name:17} {proj or 'all':16} n={len(s):3} acc={sum(V[r['id']][0] == V4.truth(r)[0] for r in s) / len(s):.3f} "
              f"recall={len(caught)}/{len(risky)} reason={sum(V4.ok_kind(V[r['id']][1], V4.truth(r)[1]) for r in caught)}/{len(caught)} "
              f"FA={sum(V[r['id']][0] for r in ok)}/{len(ok)}")
V = {r["id"]: A.product(r, preds.get(r["id"])) for r in rows}
fa = [r for r in rows if not V4.truth(r)[0] and V[r["id"]][0] and V[r["id"]][1] != "code_not_foreseen"]
print("false alarms by said kind", Counter(V[r["id"]][1] for r in fa), "by project", Counter(r["project"] for r in fa))
for r in fa:
    p = preds.get(r["id"], {})
    print(f"  {r['id'][-70:]:70} {V[r['id']][1]:8} lost={p.get('p_lost', 0):.2f} fails={p.get('p_fails', 0):.2f} detail={r.get('lost_detail')[:1]}")
