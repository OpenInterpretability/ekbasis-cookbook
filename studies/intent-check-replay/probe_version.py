import json, sys, glob
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
R = "../../agentdojo_repo/runs"
VERS = ["v1.2.2", "v1.2.1", "v1.2", "v1.1.2", "v1.1.1", "v1.1", "v1"]
def text(m):
    c = m.get("content")
    if isinstance(c, list): return "".join(b.get("content", "") or "" for b in c if isinstance(b, dict))
    return c or ""
def reproduce(log, ver):
    try:
        su = get_suite(ver, log["suite_name"]); ut = su.get_user_task_by_id(log["user_task_id"])
        env = ut.init_environment(su.load_and_inject_default_environment(log.get("injections") or {}))
    except Exception as e:
        return None
    rt = FunctionsRuntime(su.tools); ok = tot = 0
    for m in log["messages"]:
        if m["role"] == "tool" and m.get("tool_call"):
            c = m["tool_call"]; res, err = rt.run_function(env, c["function"], c["args"], raise_on_error=False)
            got = err if err else tool_result_to_str(res); want = m.get("error") or text(m)
            tot += 1; ok += (got.strip() == want.strip())
    return ok, tot
for f in sys.argv[1:]:
    log = json.load(open(f)); print(f.split("runs/")[1], {v: reproduce(log, v) for v in VERS})
