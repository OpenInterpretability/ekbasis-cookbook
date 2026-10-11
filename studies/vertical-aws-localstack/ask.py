"""Ask Ekbasis about each labelled scenario (concurrency 1, resumable; waits on 429). usage: ask.py <outdir> dev|test [ids...]"""
import json
import os
import sys
import time

from ekbasis.client import Ekbasis

import guard as G
import rule as R

ROOT = os.path.dirname(os.path.abspath(__file__))
key = open(os.path.expanduser("~/.config/ekbasis/study_api_key")).read().strip()
client = Ekbasis(url="https://openinterp.org/api/v1", api_key=key, timeout=180, surface="aws-guard-pilot")
out = os.path.join(ROOT, sys.argv[1])
os.makedirs(out, exist_ok=True)
split = sys.argv[2]          # dev | test
labels = json.load(open(os.path.join(ROOT, f"labels_{split}.json")))
ids = [int(x) for x in sys.argv[3:]] or sorted(int(k) for k in labels)
for i in ids:
    f = os.path.join(out, f"s{i}.json")
    if os.path.exists(f):
        continue
    d = os.path.join(ROOT, "runs", f"s{i}")
    plan, facts = json.load(open(f"{d}/plan.json")), json.load(open(f"{d}/facts.json"))
    state = G.build_state(plan, facts)
    t = time.time()
    for attempt in range(6):
        try:
            ans = client.ask(state, G.QUESTIONS)
            break
        except Exception as e:
            err = str(e)[:300]
            time.sleep(60 if "429" in err else 5)
    else:
        json.dump({"id": i, "error": err}, open(f + ".err", "w"))
        print(f"s{i} ERROR {err}", flush=True)
        continue
    p = {k: a.p_yes for k, a in ans.items()}
    rec = {"id": i, "p": p, "verdict": G.decide(p), "rule": R.rule(plan), "state": state,
           "request_id": client.last_request_id, "usage": client.last_usage, "s": round(time.time() - t, 2)}
    json.dump(rec, open(f, "w"), indent=1)
    print(f"s{i} {json.dumps({k: round(v, 3) for k, v in p.items()})} {rec['s']}s", flush=True)
