"""Code-only checks fixed before any Ekbasis call: the checker-text detector on benign AgentDojo tool outputs (every
ground-truth call of every user task, clean environment) and on the attack texts; the delegation gate on front-2 items."""
import json, collections
from agentdojo.task_suite.load_suites import get_suite
from ekbasis.intent import addressed_segments, delegated_sources, unnamed_destinations
from build_items import run_calls
n_out = n_hit = 0; hits = []
for s in ["workspace", "travel", "banking", "slack"]:
    su = get_suite("v1.2.2", s)
    for u, t in su.user_tasks.items():
        env = t.init_environment(su.load_and_inject_default_environment({}))
        for e in run_calls(su, env, t.ground_truth(env.model_copy(deep=True))):
            n_out += 1
            seg = addressed_segments(e["result"])
            if seg: n_hit += 1; hits.append((s, u, e["name"], seg[:2]))
print(f"benign tool outputs: {n_out}, with a segment addressed to the checker: {n_hit}")
for h in hits: print("  ", h)
rows = [json.loads(l) for l in open("items.jsonl")]
c = collections.Counter()
for r in rows:
    if r["attack"] != "none":
        c[(r["attack"], any(addressed_segments(e["result"]) for e in r["events"]))] += 1
print("items with addressed text, by attack:", sorted(c.items()))
g = collections.Counter()
for r in rows:
    if "f2" in r["fronts"]:
        src = delegated_sources(r["request"]); d = unnamed_destinations(r["request"], r["action"])
        g[(r["kind"], "framing" if src and not d else "standard")] += 1
print("front 2 gate:", sorted(g.items()))
