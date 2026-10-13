"""Recompute the v4 numbers of the public report from the published files (no cluster, no API, no key needed).

    python3 recompute_chain4.py            # writes recompute_chain4_output.json and prints it (needs scipy)

Same definitions as the sealed chain4/analyze_chain4.py: the guard's wall-clock seconds per run are the sum of the
guard_ms of its decisions; tokens and unanswered calls come from each run's judge calls; tests with SciPy."""
import json
import os
import statistics as st

from scipy.stats import binomtest, wilcoxon

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "chain4", "results")
SONNET_IN, SONNET_OUT, EKB_IN = 2.0, 10.0, 0.30
rows = [json.loads(l) for l in open(os.path.join(RES, "runs_h.jsonl"))]
by = {(r["id"], r["cond"], r["seed"]): r for r in rows}
for r in rows:
    p = os.path.join(RES, "forecast_calls", f"{r['rid']}.jsonl")
    cs = [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    r["m"] = {"wall": sum(g.get("guard_ms") or 0 for g in r.get("guard") or []) / 1000,
              "in": sum(c.get("in") or 0 for c in cs), "out": sum(c.get("out") or 0 for c in cs), "n": len(cs),
              "fail": sum(1 for c in cs if not c.get("ok"))}
    r["m"]["usd"] = (EKB_IN * r["m"]["in"] if r["cond"] == "chain_ekb" else SONNET_IN * r["m"]["in"] + SONNET_OUT * r["m"]["out"]) / 1e6
out = {"runs": len(rows), "arms": {}}
for c in ("chain_ekb", "chain_glm"):
    A = [r for r in rows if r["cond"] == c]
    H = [r for r in A if r["kind"] == "harm"]
    out["arms"][c] = {"harmful_runs": sum(bool(r.get("harm")) for r in H), "harm_runs": len(H),
                      "tasks_completed": sum(bool(r.get("success")) for r in H),
                      "controls_completed": sum(bool(r.get("success")) for r in A if r["kind"] != "harm"),
                      "guard_wall_seconds_median": round(st.median(r["m"]["wall"] for r in A), 1),
                      "usd_per_run_mean": round(st.mean(r["m"]["usd"] for r in A), 4),
                      "judge_calls": sum(r["m"]["n"] for r in A), "judge_calls_without_answer": sum(r["m"]["fail"] for r in A),
                      "questions_to_the_user": sum(len(r.get("replies") or []) for r in A),
                      "agent_seconds_median": round(st.median(r.get("agent_secs") or 0 for r in A), 1)}
keys = sorted({(r["id"], r["seed"]) for r in rows})
P = [(by[(i, "chain_ekb", s)], by[(i, "chain_glm", s)]) for i, s in keys if (i, "chain_ekb", s) in by and (i, "chain_glm", s) in by]
PH = [(e, g) for e, g in P if e["kind"] == "harm"]
x, y = [e["m"]["wall"] for e, _ in P], [g["m"]["wall"] for _, g in P]
out["H1_safety"] = {"harm_ekbasis": sum(bool(e["harm"]) for e, _ in PH), "harm_glm": sum(bool(g["harm"]) for _, g in PH)}
out["H2_speed"] = {"median_ratio": round(st.median(y) / st.median(x), 1), "ekbasis_lower": sum(a < b for a, b in zip(x, y)),
                   "pairs": len(P), "wilcoxon_p": float(f"{wilcoxon(x, y, alternative='less').pvalue:.3g}")}
ce, cg = [e["m"]["usd"] for e, _ in P], [g["m"]["usd"] for _, g in P]
out["H3_cost"] = {"wilcoxon_p": float(f"{wilcoxon(ce, cg, alternative='less').pvalue:.3g}")}
oe = sum(bool(e["success"]) and not bool(g["success"]) for e, g in PH)
og = sum(bool(g["success"]) and not bool(e["success"]) for e, g in PH)
out["H5_completion"] = {"only_ekbasis": oe, "only_glm": og, "mcnemar_two_sided_p": float(f"{binomtest(oe, oe + og, 0.5).pvalue:.3g}")}
json.dump(out, open(os.path.join(HERE, "recompute_chain4_output.json"), "w"), indent=1)
print(json.dumps(out, indent=1))
