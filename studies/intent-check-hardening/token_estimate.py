"""Estimates agent tokens per AgentDojo run from the calibration traces (chars/4, tool schemas included)."""
import json, glob, statistics
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.agent_pipeline.llms.openai_llm import _function_to_openai
schema = {s: len(json.dumps([_function_to_openai(f) for f in get_suite("v1.2.2", s).tools])) for s in
          ["workspace", "travel", "banking", "slack"]}
ins, outs, turns = [], [], []
for f in glob.glob("calib_out/logs/*/*/*/*/*.json"):
    d = json.load(open(f)); msgs = d["messages"]; s = d["suite_name"]
    tin = tout = 0; ctx = 0; nt = 0
    for m in msgs:
        size = len(json.dumps(m.get("content"))) + len(json.dumps(m.get("tool_calls") or ""))
        if m["role"] == "assistant":
            tin += (ctx + schema[s]) / 4; tout += size / 4; nt += 1
        ctx += size
    ins.append(tin); outs.append(tout); turns.append(nt)
print(f"runs {len(ins)}; input tokens/run mean {statistics.mean(ins):.0f} p90 {sorted(ins)[int(.9*len(ins))]:.0f}; "
      f"output/run {statistics.mean(outs):.0f}; LLM calls/run {statistics.mean(turns):.1f}")
