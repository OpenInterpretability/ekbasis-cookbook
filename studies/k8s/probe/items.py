"""WS-K8S Phase 0: the forecasters' prompts from pass A (SPEC_probe.md §5–6). One item per (scenario, forecaster).
    python3 items.py   -> data/items.jsonl
E0/E1: (state, questions) for Ekbasis; H0/H1/S1: one prompt text for Claude. Rules: the pair's rule ids (k8s_rules)."""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.environ.get("CLAUDE_JOB_DIR", "<job>"), "tmp",
                                "ekbasis_venv", "lib", "python3.9", "site-packages"))
from ekbasis import prompts as P  # noqa: E402

import k8s_rules as R  # noqa: E402

VERSION = json.load(open(os.path.join(HERE, "cluster_info.json")))["server"]


def build(rows):
    out = []
    for r in rows:
        if "error" in r or "summary" not in r:
            continue
        for cond, rules in (("E0", None), ("E1", r["rules"])):
            st, qs = R.ekbasis_prompt(P, VERSION, r["summary"], r["command"], rule_ids=rules)
            out.append({"id": r["id"], "cond": cond, "state": st, "questions": qs})
        for cond, rules in (("H0", None), ("H1", r["rules"]), ("S1", r["rules"])):
            out.append({"id": r["id"], "cond": cond, "prompt": R.llm_prompt(P, VERSION, r["summary"], r["command"], rule_ids=rules)})
    return out


if __name__ == "__main__":
    rows = [json.loads(l) for l in open(os.path.join(HERE, "data", "truth_A.jsonl"))]
    items = build(rows)
    with open(os.path.join(HERE, "data", "items.jsonl"), "w") as f:
        for it in items:
            f.write(json.dumps(it, sort_keys=True) + "\n")
    print(len(items), "items from", len(rows), "pass-A rows")
