"""WS-K8S: what the Ekbasis guard would cost per run at the hosted API price (US$0.04 per 1M input tokens, no output
charge), next to the Sonnet guard. Descriptive, not pre-registered (added 2026-10-10).

The guard logged, for every Ekbasis request, the length in characters of the state it sent (`state_chars`), the rules it
repeated before each question (`rules`) and whether it was a safer-way check (12 questions instead of 11), but not the
state text itself. So:
  1. Billing rule, measured: the hosted backend reports `usage.input_tokens`; with read_once off (as in the study) it
     counts the state once per question (1 question 1,463 tokens, 2: 3,002, 3: 4,446, 7: 10,353 on one state).
  2. The question part is exact: each request's questions are rebuilt with the study's own code (guard_lib.all_questions
     + ekbasis.prompts.recap_all with the logged rules) and counted by the backend on a one-character state.
  3. The state part is estimated from `state_chars` with a line fitted on the 40 real Phase 0 states (same world layout,
     same summarizer): tokens added by the state, against its characters.
  4. Check: the 10 first exact Phase 0 Ekbasis requests (state + its 7 questions, byte-identical to what was sent) are
     replayed, and the method's prediction is compared with the backend's count.
Requests go to https://api.openinterp.org/v1/systemone; the key is read from the EKBASIS_API_KEY environment variable and never
printed. Spend: none (the key is ours).
    python3 cost_ekbasis_tokens.py > cost_ekbasis_tokens_output.json"""
import json
import os
import statistics as st
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "phase1", "harness"))
import guard_lib as GL  # noqa: E402  (frozen; only its question builder)
import k8s_rules as R  # noqa: E402
from ekbasis import prompts as P  # noqa: E402

URL = "https://api.openinterp.org/v1/systemone"
KEY = os.environ["EKBASIS_API_KEY"]
PRICE = 0.04 / 1e6
SONNET_PER_RUN = None  # read from the runs below


def tokens(state, qs):
    req = urllib.request.Request(URL, data=json.dumps({"state": state, "questions": qs}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}",
                                          "User-Agent": "ekbasis-client/0.1.6"})
    return json.load(urllib.request.urlopen(req, timeout=300))["usage"]["input_tokens"]


def questions(rules, with_fulfills):
    qs = GL.all_questions(with_fulfills)
    return P.recap_all(qs, R.rule_texts(rules)) if rules else qs


# ------------------------------------------------------------------------------------------------ calibration on real states
items = [json.loads(l) for l in open(os.path.join(HERE, "probe", "data", "items.jsonl"))]
e1 = [x for x in items if x["cond"] == "E1"]
q0 = {"q": {"type": "boolean", "instructions": "Does it fail?", "criteria": {"true": "yes", "false": "no"}}}
base = tokens("x", q0)
pts = [(len(x["state"]), tokens(x["state"], q0) - base) for x in e1]
n = len(pts)
mx, my = sum(c for c, _ in pts) / n, sum(t for _, t in pts) / n
slope = sum((c - mx) * (t - my) for c, t in pts) / sum((c - mx) ** 2 for c, _ in pts)
icpt = my - slope * mx
resid = [t - (icpt + slope * c) for c, t in pts]
state_tok = lambda chars: icpt + slope * chars  # noqa: E731

# ------------------------------------------------------------------------------------------------ check on 10 exact replays
check = []
for x in e1[:10]:
    meas = tokens(x["state"], x["questions"])
    pred = tokens("x", x["questions"]) + len(x["questions"]) * state_tok(len(x["state"]))
    check.append({"id": x["id"], "measured": meas, "predicted": round(pred), "error_pct": round(100 * (pred - meas) / meas, 2)})

# ------------------------------------------------------------------------------------------------ the study's Ekbasis requests
qcache = {}
per_run = {}
for f in ("runs_h.jsonl", "runs_s.jsonl"):
    for l in open(os.path.join(HERE, "phase1", "results", f)):
        r = json.loads(l)
        if r["cond"] != "ask_ekbasis":
            continue
        reqs = []
        for g in r.get("guard") or []:
            m = g.get("meta") or {}
            if m.get("ms"):
                reqs.append((m["state_chars"], tuple(m["rules"]), False))
            for t in g.get("safer_tried") or []:
                tm = t.get("meta") or {}
                if tm.get("ms"):
                    reqs.append((tm["state_chars"], tuple(tm["rules"]), True))
        tot = 0.0
        for chars, rules, fz in reqs:
            k = (rules, fz)
            if k not in qcache:
                qs = questions(list(rules), fz)
                qcache[k] = (tokens("x", qs), len(qs))
            qt, nq = qcache[k]
            tot += qt + nq * state_tok(chars)
        per_run.setdefault(r["agent"], []).append({"rid": r["rid"], "requests": len(reqs), "tokens": tot})

son = []
for l in open(os.path.join(HERE, "phase1", "results", "runs_h.jsonl")):
    r = json.loads(l)
    if r["cond"] == "ask_sonnet":
        son.append(sum(((g.get("meta") or {}).get("cost") or 0) + sum(((t.get("meta") or {}).get("cost") or 0)
                                                                      for t in g.get("safer_tried") or [])
                       for g in r.get("guard") or []))
sonnet_per_run = st.mean(son)

out = {"descriptive_not_preregistered": True, "price_usd_per_1M_input_tokens": 0.04,
       "billing_rule": "state counted once per question (read_once off, as in the study)",
       "calibration": {"states": n, "tokens_per_state_char": round(slope, 4), "intercept": round(icpt, 1),
                       "residual_abs_max_tokens": round(max(abs(x) for x in resid), 1),
                       "residual_sd_tokens": round(st.pstdev(resid), 1)},
       "check_on_10_exact_phase0_replays": check,
       "check_mean_abs_error_pct": round(st.mean(abs(c["error_pct"]) for c in check), 2),
       "question_sets_counted": len(qcache), "by_agent": {}}
for agent, rs in per_run.items():
    tk = [x["tokens"] for x in rs]
    out["by_agent"][agent] = {"runs": len(rs), "requests": sum(x["requests"] for x in rs),
                              "tokens_per_run_median": round(st.median(tk)), "tokens_per_run_mean": round(st.mean(tk)),
                              "tokens_per_request_mean": round(sum(tk) / sum(x["requests"] for x in rs)),
                              "usd_per_run_median": round(st.median(tk) * PRICE, 5),
                              "usd_per_run_mean": round(st.mean(tk) * PRICE, 5)}
h = out["by_agent"]["haiku"]
out["haiku_comparison"] = {
    "ekbasis_guard_usd_per_run_mean": h["usd_per_run_mean"], "sonnet_guard_usd_per_run_mean": round(sonnet_per_run, 4),
    "sonnet_over_ekbasis_cost_ratio": round(sonnet_per_run / h["usd_per_run_mean"], 1),
    "harm_ekbasis_guard": "2/36", "harm_sonnet_guard": "1/36",
    "note": "Sonnet figure = what was actually paid through `claude -p` (includes the CLI's own prompt overhead); "
            "Ekbasis figure = the hosted list price applied to the study's requests (the study itself ran on a local Mac)."}
print(json.dumps(out, indent=1))
