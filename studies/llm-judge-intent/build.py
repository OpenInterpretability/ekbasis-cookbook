"""Sample the items (PREREG) and capture the exact state + question intent_check sends, without calling any model."""
import json, random, sys
sys.path.insert(0, "../blindagem/replay/client")
from ekbasis.intent import intent_check
R = "../blindagem/replay"
runs = {json.loads(l)["id"]: json.loads(l) for l in open(f"{R}/runs.jsonl")}
ans = {}
for l in open(f"{R}/out/answers.jsonl"):
    a = json.loads(l)
    if not a["delegation"]:
        ans[(a["id"], a["j"])] = a["p"]
rng = random.Random(20261011)
att = sorted([r for r in runs.values() if r["kind"] == "attack"], key=lambda r: int(r["id"]))
ben_calls = sorted([(r["id"], j) for r in runs.values() if r["kind"] != "attack" for j in range(len(r["calls"]))],
                   key=lambda x: (int(x[0]), x[1]))
items = [(r["id"], int(r["completing"]), "attack") for r in rng.sample(att, 250)]
items += [(i, j, "benign") for i, j in rng.sample(ben_calls, 250)]

class Capture:
    def ask(self, state, questions, **kw):
        self.state, self.q = state, questions
        raise StopIteration
out = []
for rid, j, kind in items:
    run = runs[rid]; c = run["calls"][j]; cap = Capture()
    try:
        intent_check(run["request"], c["events"], c["action"], client=cap, delegation=False)
    except StopIteration:
        pass
    q = next(iter(cap.q.values()))
    out.append({"id": rid, "j": j, "kind": kind, "model": run["model"], "state": cap.state, "question": q, "ekb_p": ans.get((rid, j))})
with open("items.jsonl", "w") as f:
    for o in out: f.write(json.dumps(o) + "\n")
print(len(out), sum(o["ekb_p"] is None for o in out), "missing ekb p")
