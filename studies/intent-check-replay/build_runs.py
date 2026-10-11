"""Builds the replay items from the PUBLISHED AgentDojo trajectories (agentdojo_repo/runs), no LLM call.

For each model in MODELS: every important_instructions run with security == True (attack) and every run without
injections (none/none.json, benign). Each tool call of the trajectory, in order, becomes one judgment: the events are
every tool result logged before the assistant message that made the call (as intent_defense builds them), the action is
the call. Attack runs: the trajectory's calls are re-executed in the injected environment (the injections stored in the
log) and after each one the injection task's security_from_traces() / security() is checked with an empty model output
(AgentDojo's own order); the first call after
which it holds is the COMPLETING call. Judgments stop there. A run whose replay never completes the attack (a goal met
by text, or a replay that diverges) is excluded and counted.

Benchmark version per log: its benchmark_version if logged; else, within the family with the model's pair count (629:
v1..v1.1.2, 949: v1.2..v1.2.2), the version that reproduces the most logged tool outputs; ties go to the first release
of the family (v1, v1.2).

usage: build_runs.py out.jsonl
"""
import json
import sys
from glob import glob

from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite

RUNS = "../../agentdojo_repo/runs"
MODELS = ["gpt-4o-2024-05-13", "gpt-4-0125-preview", "claude-3-5-sonnet-20240620", "claude-3-7-sonnet-20250219",
          "gemini-1.5-pro-001", "gemini-2.0-flash-001", "meta-llama_Llama-3-70b-chat-hf",
          "meta-llama_Llama-3.3-70B-Instruct"]
FAMILY = {629: ["v1", "v1.1", "v1.1.1", "v1.1.2"], 949: ["v1.2", "v1.2.1", "v1.2.2"]}


def text(m):
    c = m.get("content")
    if isinstance(c, list):
        return "".join(b.get("content", "") or "" for b in c if isinstance(b, dict))
    return c or ""


def env_for(log, ver):
    su = get_suite(ver, log["suite_name"])
    ut = su.get_user_task_by_id(log["user_task_id"])
    return su, ut, ut.init_environment(su.load_and_inject_default_environment(log.get("injections") or {}))


def reproduced(log, ver):
    try:
        su, _, env = env_for(log, ver)
    except Exception:
        return -1
    rt, ok = FunctionsRuntime(su.tools), 0
    for m in log["messages"]:
        if m["role"] == "tool" and m.get("tool_call"):
            c = m["tool_call"]
            try:
                res, err = rt.run_function(env, c["function"], c["args"], raise_on_error=False)
            except Exception as e:
                res, err = None, str(e)
            ok += ((err if err else tool_result_to_str(res)).strip() == (m.get("error") or text(m)).strip())
    return ok


def choose_version(log, n_pairs):
    if log.get("benchmark_version"):
        return log["benchmark_version"]
    fam = FAMILY[n_pairs]
    scores = [(reproduced(log, v), -i, v) for i, v in enumerate(fam)]
    return max(scores)[2]


def judgments(log):
    out, events = [], []
    for m in log["messages"]:
        if m["role"] == "assistant" and m.get("tool_calls"):
            snap = list(events)
            for c in m["tool_calls"]:
                out.append({"events": snap, "action": {"name": c["function"], "input": c["args"]}})
        if m["role"] == "tool" and m.get("tool_call"):
            events.append({"kind": "tool", "name": m["tool_call"]["function"], "input": m["tool_call"]["args"],
                           "result": m.get("error") or text(m)})
    return out


def completing_index(log, ver):
    """Index (in call order) of the first call after which the injection task's security() holds, or None."""
    su, _, env = env_for(log, ver)
    it = su.get_injection_task_by_id(log["injection_task_id"])
    pre = env.model_copy(deep=True)
    rt, k, traces = FunctionsRuntime(su.tools), 0, []
    for m in log["messages"]:
        if m["role"] == "assistant" and m.get("tool_calls"):
            for c in m["tool_calls"]:
                try:
                    rt.run_function(env, c["function"], c["args"], raise_on_error=False)
                except Exception:
                    pass
                traces.append(FunctionCall(function=c["function"], args=c["args"]))
                try:   # AgentDojo's own order: security_from_traces when the task defines it, else security
                    done = it.security_from_traces("", pre, env, traces)
                    if done is None:
                        done = it.security("", pre, env)
                    if done:
                        return k
                except Exception:
                    pass
                k += 1
    return None


def main(out_path):
    rows, excluded = [], []
    for model in MODELS:
        att = sorted(glob(f"{RUNS}/{model}/*/user_task_*/important_instructions/injection_task_*.json"))
        ben = sorted(glob(f"{RUNS}/{model}/*/user_task_*/none/none.json"))
        n_pairs = len(att)
        for f in att + ben:
            log = json.load(open(f))
            kind = "attack" if "/important_instructions/" in f else "benign"
            if kind == "attack" and log.get("security") is not True:
                continue
            ver = choose_version(log, n_pairs)
            js = judgments(log)
            row = {"model": model, "suite": log["suite_name"], "ut": log["user_task_id"],
                   "it": log.get("injection_task_id"), "kind": kind, "version": ver,
                   "request": next(text(m) for m in log["messages"] if m["role"] == "user")}
            if kind == "attack":
                k = completing_index(log, ver)
                if k is None:
                    excluded.append({"model": model, "file": f.split("runs/")[1], "n_calls": len(js)})
                    continue
                js = js[: k + 1]
                row["completing"] = k
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
