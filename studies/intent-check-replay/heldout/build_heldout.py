"""Held-out replay items (no LLM call): the same construction as ../build_runs.py, over the published AgentDojo runs of
attacks OTHER than important_instructions (and its renamed variants), on every model that has them; benign runs of the
models not used in the first replay. Each attack run also gets the function names of its user task's ground truth
(to mark parameter-swap cases).

usage: build_heldout.py out.jsonl
"""
import json
import sys
from glob import glob

sys.path.insert(0, "..")
import build_runs as br  # noqa: E402

br.RUNS = "../../../agentdojo_repo/runs"
ATTACKS = {"gpt-4o-2024-05-13": ["tool_knowledge", "injecagent", "direct", "ignore_previous"],
           "meta-llama_Llama-3.3-70B-Instruct": ["direct", "ignore_previous"],
           "meta-llama_Llama-3.3-70B-Instruct-repeat_user_prompt": ["direct", "ignore_previous"],
           "Meta-SecAlign-70B": ["direct", "ignore_previous"],
           "Meta-SecAlign-70B-repeat_user_prompt": ["direct", "ignore_previous"]}
NEW_BENIGN = ["meta-llama_Llama-3.3-70B-Instruct-repeat_user_prompt", "Meta-SecAlign-70B",
              "Meta-SecAlign-70B-repeat_user_prompt"]


def gt_functions(log, ver):
    su, ut, env = br.env_for(log, ver)
    try:
        return sorted({c.function for c in ut.ground_truth(env.model_copy(deep=True))})
    except Exception:
        return []


def main(out_path):
    rows, excluded = [], []
    jobs = [(m, a, f) for m, atts in ATTACKS.items() for a in atts
            for f in sorted(glob(f"{br.RUNS}/{m}/*/user_task_*/{a}/injection_task_*.json"))]
    jobs += [(m, "none", f) for m in NEW_BENIGN for f in sorted(glob(f"{br.RUNS}/{m}/*/user_task_*/none/none.json"))]
    for model, attack, f in jobs:
        log = json.load(open(f))
        if attack != "none" and log.get("security") is not True:
            continue
        n_pairs = 629 if len(glob(f"{br.RUNS}/{model}/*/user_task_*/{attack if attack != 'none' else 'direct'}/"
                                  f"injection_task_*.json")) == 629 else 949
        ver = br.choose_version(log, n_pairs)
        js = br.judgments(log)
        row = {"model": model, "attack": attack, "suite": log["suite_name"], "ut": log["user_task_id"],
               "it": log.get("injection_task_id"), "kind": "benign" if attack == "none" else "attack", "version": ver,
               "request": next(br.text(m) for m in log["messages"] if m["role"] == "user")}
        if attack != "none":
            k = br.completing_index(log, ver)
            if k is None:
                excluded.append({"model": model, "attack": attack, "file": f.split("runs/")[1], "n_calls": len(js)})
                continue
            js = js[: k + 1]
            row["completing"] = k
            row["ut_gt_functions"] = gt_functions(log, ver)
        row["calls"] = js
        rows.append(row)
    with open(out_path, "w") as fo:
        for i, r in enumerate(rows):
            r["id"] = i
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out_path.replace(".jsonl", "_excluded.jsonl"), "w") as fo:
        for e in excluded:
            fo.write(json.dumps(e) + "\n")
    print(len(rows), "runs;", sum(len(r["calls"]) for r in rows), "judgments;", len(excluded), "attack runs excluded")


if __name__ == "__main__":
    main(sys.argv[1])
