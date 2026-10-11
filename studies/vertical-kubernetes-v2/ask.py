"""Ask Ekbasis (concurrency 1) about labelled scenarios; also records R2 and R1 on the same facts (concurrency 1, resumable). usage: ask.py <outdir> <dev|test> [ids...]"""
import json
import os
import sys
import time

from ekbasis.client import Ekbasis

import guard as G
import rule2 as R2

ROOT = os.path.dirname(os.path.abspath(__file__))
key = open(os.path.expanduser("~/.config/ekbasis/study_api_key")).read().strip()
client = Ekbasis(url="https://openinterp.org/api/v1", api_key=key, timeout=300, surface="k8s-guard-v2")
out = os.path.join(ROOT, sys.argv[1])
split = sys.argv[2]
os.makedirs(out, exist_ok=True)
labels = json.load(open(os.path.join(ROOT, f"labels_{split}.json")))
ids = [int(x) for x in sys.argv[3:]] or sorted(int(k) for k in labels)
for i in ids:
    f = os.path.join(out, f"s{i}.json")
    if os.path.exists(f):
        continue
    d = os.path.join(ROOT, "runs", f"s{i}")
    fx, res = json.load(open(f"{d}/facts.json")), json.load(open(f"{d}/result.json"))
    state = G.build_state(fx, res["commands"])
    t = time.time()
    err = None
    for attempt in range(8):
        try:
            ans = client.ask(state, G.QUESTIONS)
            break
        except Exception as e:
            err = str(e)[:300]
            time.sleep(min(120, 10 * 2 ** attempt) if "429" in err or "timeout" in err.lower() else 10)
    else:
        json.dump({"id": i, "error": err}, open(f + ".err", "w"))
        print(f"s{i} ERROR {err}", flush=True)
        continue
    p = {k: a.p_yes for k, a in ans.items()}
    rec = {"id": i, "p": p, "verdict": G.decide(p), "r2": R2.rule2(fx), "r1": G.rule(fx), "state": state,
           "request_id": client.last_request_id, "usage": client.last_usage, "s": round(time.time() - t, 2)}
    json.dump(rec, open(f, "w"), indent=1)
    if split == "test":   # no per-item output on test until evaluate.py
        print(f"s{i} ok {rec['s']}s", flush=True)
    else:
        print(f"s{i} {json.dumps({k: round(v, 3) for k, v in p.items()})} {rec['s']}s", flush=True)
