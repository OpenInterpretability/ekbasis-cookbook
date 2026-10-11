"""Step 4 driver: facts for every labeled PR of a split (excluded PRs are skipped). usage: build_facts.py dev|test"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from facts import pr_facts
from ghc import ROOT

split = sys.argv[1]
cands = {f"{x['repo']}#{x['number']}": x for x in map(json.loads, open(os.path.join(ROOT, "data", f"{split}_candidates.jsonl")))}
labels = [json.loads(l) for l in open(os.path.join(ROOT, "data", f"{split}_labels.jsonl"))]
ids = [f"{l['repo']}#{l['number']}" for l in labels if l["label"] is not None]


def one(i):
    try:
        return i, pr_facts(cands[i])
    except Exception as e:  # noqa: BLE001
        return i, {"error": repr(e)[:300]}


with open(os.path.join(ROOT, "data", f"{split}_facts.jsonl"), "w") as f, ThreadPoolExecutor(4) as ex:
    for k, (i, F) in enumerate(ex.map(one, ids)):
        f.write(json.dumps({"id": i, "facts": F}) + "\n")
        if k % 25 == 0:
            print(k, i, "error" in F, flush=True)
