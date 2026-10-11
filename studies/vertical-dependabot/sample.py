"""Step 2: dev/test split by repository owner and a stratified sample, from titles only (PREREG §2). No label is read.

- One PR per (repository, package): the most recent.
- Split: sha256(owner) first 8 hex digits as an integer, mod 10 < 3 -> dev, else test. Owners never cross the split.
- Per repository: up to 3 semver-major PRs and up to 3 others, drawn at random (seed 20261011).
- Caps: 200 PRs in dev, 450 in test (repositories drawn at random, in full, until the cap).
"""
import hashlib
import json
import os
import random

from facts import semver_delta
from ghc import ROOT

SEED = 20261011
CAP = {"dev": 200, "test": 450}


def split_of(repo):
    owner = repo.split("/")[0].lower()
    return "dev" if int(hashlib.sha256(owner.encode()).hexdigest()[:8], 16) % 10 < 3 else "test"


if __name__ == "__main__":
    cands = [json.loads(l) for l in open(os.path.join(ROOT, "data", "candidates_all.jsonl"))]
    latest = {}
    for c in cands:
        k = (c["repo"], c["pkg"].lower())
        if k not in latest or c["created"] > latest[k]["created"]:
            latest[k] = c
    byrepo = {}
    for c in sorted(latest.values(), key=lambda c: (c["repo"], c["number"])):
        byrepo.setdefault(c["repo"], []).append(c)
    rng = random.Random(SEED)
    out = {"dev": [], "test": []}
    repos = sorted(byrepo)
    rng.shuffle(repos)
    for repo in repos:
        s = split_of(repo)
        items = byrepo[repo]
        maj = [c for c in items if semver_delta(c["frm"], c["to"]) == "major"]
        oth = [c for c in items if c not in maj]
        pick = rng.sample(maj, min(3, len(maj))) + rng.sample(oth, min(3, len(oth)))
        if len(out[s]) + len(pick) > CAP[s]:
            continue
        out[s] += pick
    for s, items in out.items():
        items.sort(key=lambda c: (c["repo"], c["number"]))
        with open(os.path.join(ROOT, "data", f"{s}_candidates.jsonl"), "w") as f:
            for c in items:
                f.write(json.dumps(c) + "\n")
        with open(os.path.join(ROOT, "frozen", f"{s}_ids.txt"), "w") as f:
            for c in items:
                f.write(f"{c['repo']}#{c['number']}\n")
        nmaj = sum(semver_delta(c["frm"], c["to"]) == "major" for c in items)
        print(s, len(items), "PRs,", len({c["repo"] for c in items}), "repos,", nmaj, "major,",
              sum(c["eco"] == "pip" for c in items), "pip")
