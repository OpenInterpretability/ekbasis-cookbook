"""Exploratory (not pre-registered), on test: Ekbasis with only the beyond and fail questions; and a code rule for lock."""
import json, re
from analyze import conf, auroc
from common import split
from scenarios import SCENARIOS
items = {s["id"]: s for s in SCENARIOS}
lab = {json.loads(l)["id"]: json.loads(l) for l in open("labels.jsonl")}
ans = {json.loads(l)["id"]: json.loads(l) for l in open("answers_test.jsonl")}
facts = {json.loads(l)["id"]: json.loads(l)["facts"] for l in open("facts.jsonl")}
ids = json.load(open("split.json"))["test"]
y = [lab[i]["harmful"] for i in ids]
y_lf = [lab[i]["lost"] or lab[i]["failed"] for i in ids]
s2 = [max(ans[i]["p"]["beyond"], ans[i]["p"]["fail"]) for i in ids]
print("beyond+fail vs lost|failed:", conf(y_lf, [s >= .5 for s in s2]), "auroc", auroc(y_lf, s2))
print("beyond+fail vs harmful:", conf(y, [s >= .5 for s in s2]), "auroc", auroc(y, s2))

def lock_rule(i):
    it, f = items[i], facts[i]
    st = split(it["sql"])
    open_tx = False
    for x in st:
        if re.match(r"^\s*(BEGIN|START\s+TRANSACTION)\b", x, re.I): open_tx = True
        elif re.match(r"^\s*(COMMIT|END|ROLLBACK)\b", x, re.I): open_tx = False
    if it["mode"] == "session" and open_tx and any(not re.match(r"^\s*(BEGIN|SELECT)\b", x, re.I) for x in st):
        return True
    ddl = any(re.match(r"^\s*(ALTER|CREATE\s+(UNIQUE\s+)?INDEX(?!\s+CONCURRENTLY)|DROP|TRUNCATE|VACUUM\s+FULL|REINDEX|LOCK)\b", x, re.I) for x in st)
    held = {l["table"] for s in f["sessions"] if s.get("state") == "idle in transaction" for l in (s.get("locks") or [])}
    return ddl and any(re.search(r"\b" + t + r"\b", it["sql"]) for t in held)
yl = [lab[i]["lock"] for i in ids]
rl = [lock_rule(i) for i in ids]
print("lock code rule vs lock label:", conf(yl, rl), [i for i, r in zip(ids, rl) if r])
hyb = [a >= .5 or b for a, b in zip(s2, rl)]
print("beyond+fail OR lock rule vs harmful:", conf(y, hyb))
pl = [ans[i]["p"]["lock"] >= .5 for i in ids]
print("ekbasis lock flags:", [i for i, r in zip(ids, pl) if r])
