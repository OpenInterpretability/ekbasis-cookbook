"""Step 2b: split the executed items into what the models may read and what only the analysis reads.

data/requests.jsonl: {id, state, questions}            (the only file run_ekbasis.py / run_glm.py open)
data/labels.jsonl:   {id, repo, stratum, label, label_tx, errors, lost_detail, mechanisms, synthetic_cast}
data/dataset_card.json: counts, hashes of both files.
"""
from __future__ import annotations

import hashlib
import json
import os

import statebuild as SB
from analysis import load_items, mechanisms, synthetic_cast

ROOT = os.path.dirname(os.path.abspath(__file__))


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    items = load_items(included_only=True)
    rq, lb = os.path.join(ROOT, "data", "requests.jsonl"), os.path.join(ROOT, "data", "labels.jsonl")
    with open(rq, "w") as f:
        for it in items:
            f.write(json.dumps({"id": it["id"], "state": it["state"], "questions": SB.QUESTIONS,
                                "n_statements": len(it["statements"]), "est_tokens": it["state_meta"]["est_tokens"]}) + "\n")
    with open(lb, "w") as f:
        for it in items:
            f.write(json.dumps({"id": it["id"], "repo": it["repo"], "github": it["github"], "commit": it["commit"],
                                "path": it["path"], "stratum": it["stratum"], "label": it["label"],
                                "label_tx": it["label_tx"], "errors": it["run"]["errors"],
                                "lost_detail": it["run"]["lost_detail"], "mechanisms": mechanisms(it),
                                "synthetic_cast": synthetic_cast(it)}) + "\n")
    card = {"items": len(items), "requests_sha256": sha(rq), "labels_sha256": sha(lb),
            "lost": sum(it["label"]["lost"] for it in items), "fails": sum(it["label"]["fails"] for it in items),
            "half_applied": sum(it["label"]["half_applied"] for it in items)}
    json.dump(card, open(os.path.join(ROOT, "data", "dataset_card.json"), "w"), indent=1)
    print(card)


if __name__ == "__main__":
    main()
