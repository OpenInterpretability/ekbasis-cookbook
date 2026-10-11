"""Eval v3, step 0 (text only): a NEW sample from the migrations the study never drew. Same frame (frozen frame.py:
enumeration, size filter, first migration excluded, strata A/B/C by the same patterns), new seed, smaller caps.
kratos is left out: its pop layout (one migration in several dialect files) is not what the product discovers."""
import json, os, random, sys
from collections import Counter
HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.join(os.path.dirname(HERE), "pr_study")
SEED = "20261011:v3"
CAPS = {"A": 16, "B": 8, "C": 4}
frame = [json.loads(l) for l in open(os.path.join(STUDY, "data", "frame.jsonl"))]
used = {(r["repo"], r["mig"]) for r in map(json.loads, open(os.path.join(STUDY, "data", "sample.jsonl")))}
pick = []
for repo in sorted({r["repo"] for r in frame} - {"kratos"}):
    pool = [r for r in frame if r["repo"] == repo and r["size_ok"] and r["idx"] > 0 and (repo, r["mig"]) not in used]
    rng = random.Random(f"{SEED}:{repo}")
    for st in "ABC":
        s = sorted([r for r in pool if r["stratum"] == st], key=lambda r: r["idx"])
        pick += rng.sample(s, min(CAPS[st], len(s)))
pick.sort(key=lambda r: (r["repo"], r["idx"]))
with open(os.path.join(HERE, "data", "sample_v3.jsonl"), "w") as f:
    for r in pick:
        f.write(json.dumps(r) + "\n")
print(len(pick), dict(Counter(r["stratum"] for r in pick)), dict(Counter(r["repo"] for r in pick)))
