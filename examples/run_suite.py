#!/usr/bin/env python3
"""Run a scenario suite (JSONL) against an Ekbasis server and score it.

Usage:
    EKBASIS_URL=http://your-server:8010 python run_suite.py scenarios_intensive.jsonl
    EKBASIS_URL=https://openinterp.org/api/v1 EKBASIS_API_KEY=ekb_... python run_suite.py scenarios_intensive.jsonl

Each line: {"id", "domain", "state", "question": {...}, "expect"}
    expect: int    -> index into question.options that is the correct answer
            bool   -> noul/boolean expected value (true/false)
            "conf<X" / "conf>X" -> confidence threshold check (calibration)
            "obs"  -> ambiguous by design; answer is recorded, not scored

Commands are NEVER executed: the suite only asks the model what would happen.
"""
import json, os, sys, time, urllib.request
from collections import defaultdict

URL = os.environ.get("EKBASIS_URL", "http://127.0.0.1:8000") + "/v1/systemone"

def ask(state, question):
    body = json.dumps({"state": state, "questions": {"q": question}}).encode()
    t0 = time.time()
    headers = {"Content-Type": "application/json", "User-Agent": "ekbasis-cookbook/run_suite"}
    if os.environ.get("EKBASIS_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["EKBASIS_API_KEY"]
    r = json.load(urllib.request.urlopen(urllib.request.Request(URL, body, headers), timeout=90))
    return r["answers"]["q"], time.time() - t0

def main(path):
    cases = [json.loads(l) for l in open(path) if l.strip()]
    by_dom, lat = defaultdict(lambda: [0, 0]), defaultdict(list)
    PASS = FAIL = OBS = 0
    for c in cases:
        a, dt = ask(c["state"], c["question"])
        lat[c["domain"]].append(dt)
        e = c["expect"]
        if e == "obs":
            ok, OBS, res = True, OBS + 1, "obs"
        elif isinstance(e, str) and e.startswith("conf"):
            op = e[4]; thr = float(e[5:])
            ok = (a["confidence"] < thr) if op == "<" else (a["confidence"] >= thr)
            res = f"conf {a['confidence']:.2f} vs {op}{thr}"
        elif isinstance(e, bool):
            ok = (a["noul"] >= 0.5) == e
            res = f"p(true) {a['noul']:.2f} (expect {'true' if e else 'false'})"
        else:
            opts = c["question"].get("options") or []
            ok = a["choice"] == opts[e]
            res = f"'{a['choice'][:52]}' conf {a['confidence']:.2f}"
        by_dom[c["domain"]][0 if ok else 1] += 1
        PASS, FAIL = PASS + (ok and e != "obs"), FAIL + (not ok)
        print(f"  {'PASS' if ok else 'FAIL':4s} | {c['domain']:8s} | {c['id']:26s} | {res} | {dt:.2f}s")
    print("\n=== by domain ===")
    for d, (p, f) in sorted(by_dom.items()):
        n = p + f
        print(f"  {d:8s}: {p}/{n} = {p/n*100:.0f}%  (mean latency {sum(lat[d])/len(lat[d]):.2f}s)")
    scored = PASS + FAIL
    print(f"\n=== TOTAL: PASS={PASS} FAIL={FAIL} OBS={OBS} of {len(cases)} ({PASS/scored*100:.0f}% of scored) ===")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "scenarios_intensive.jsonl")
