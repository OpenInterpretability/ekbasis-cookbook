"""WS-K8S Phase 1: descriptive extras for the report (SPEC §7 secondary items; no verdicts).
Guard time per run and per check, forecaster latency per request, Sonnet forecaster spend per run, agent spend and time
per run; and the list of runs with harm in the guard conditions, for review."""
import json
import os
import statistics as st
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "results")
rows = []
for p in ("h", "s"):
    fp = os.path.join(RES, f"runs_{p}.jsonl")
    if os.path.exists(fp):
        rows += [json.loads(l) for l in open(fp)]


def q(xs, f):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(f * (len(xs) - 1)))] if xs else None


by = defaultdict(list)
for r in rows:
    by[(r["agent"], r["cond"])].append(r)
out = {}
for (agent, cond), rs in sorted(by.items()):
    per_run_guard = [sum((g.get("guard_ms") or 0) for g in r.get("guard") or []) / 1000 for r in rs]
    per_req = [((g.get("meta") or {}).get("ms") or 0) / 1000 for r in rs for g in r.get("guard") or [] if (g.get("meta") or {}).get("ms")]
    per_req += [((t.get("meta") or {}).get("ms") or 0) / 1000 for r in rs for g in r.get("guard") or []
                for t in g.get("safer_tried") or [] if (t.get("meta") or {}).get("ms")]
    son = [sum(((g.get("meta") or {}).get("cost") or 0) + sum(((t.get("meta") or {}).get("cost") or 0)
                                                             for t in g.get("safer_tried") or []) for g in r.get("guard") or [])
           for r in rs]
    n_req = [sum((1 if (g.get("meta") or {}).get("ms") else 0) + sum(1 for t in g.get("safer_tried") or [] if (t.get("meta") or {}).get("ms"))
                 for g in r.get("guard") or []) for r in rs]
    out[f"{agent}/{cond}"] = {
        "runs": len(rs),
        "agent_secs_median": st.median([r.get("agent_secs") or 0 for r in rs]),
        "agent_cost_mean": round(st.mean([r.get("cost_usd") or 0 for r in rs]), 4),
        "guard_secs_per_run_median": round(st.median(per_run_guard), 1) if per_run_guard else None,
        "guard_secs_per_run_p90": round(q(per_run_guard, 0.9), 1) if per_run_guard else None,
        "forecaster_requests_per_run_mean": round(st.mean(n_req), 2) if n_req else None,
        "forecaster_secs_per_request_median": round(st.median(per_req), 1) if per_req else None,
        "forecaster_secs_per_request_p90": round(q(per_req, 0.9), 1) if per_req else None,
        "sonnet_forecaster_cost_per_run_mean": round(st.mean(son), 4) if son else None,
        "harm_runs": [f"{r['id']} s{r['seed']} ({r['rid']})" for r in rs if r.get("harm")],
    }
print(json.dumps(out, indent=1, ensure_ascii=False))
json.dump(out, open(os.path.join(RES, "extra_stats.json"), "w"), indent=1)
