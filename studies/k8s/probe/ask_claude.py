"""WS-K8S Phase 0: Claude as forecaster (H0, H1: Haiku 4.5 without/with rules, thinking off; S1: Sonnet 5.5 with rules,
Claude Code's default thinking). `claude -p`, no tools, one call per item, a few in parallel. Unparseable reply: one
retry, then p = 0.5 for every question (an abstention). Usage limit (HTTP 429): wait 20 min and retry, never recorded.
Every call's cost goes to ../spend.jsonl.
    python3 ask_claude.py [--conds H0 H1 S1] [--parallel 4]   -> data/answers_claude.jsonl"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SPEND = os.path.join(HERE, "..", "spend.jsonl")
OUT = os.path.join(HERE, "data", "answers_claude.jsonl")
LOCK = threading.Lock()
QKEYS = ["fails", "pods_terminated", "outage", "data_lost", "replicas_short", "deletes_unnamed", "restart_breaks"]
AGENT = {"H0": ("haiku", {"MAX_THINKING_TOKENS": "0"}), "H1": ("haiku", {"MAX_THINKING_TOKENS": "0"}),
         "S1": ("sonnet", {})}


def parse(text):
    for m in re.finditer(r"\{[^{}]*\}", text or "", re.S):
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if all(k in d for k in QKEYS):
            try:
                ps = {k: float(d[k]) for k in QKEYS}
            except (TypeError, ValueError):
                continue
            if all(0.0 <= v <= 1.0 for v in ps.values()):
                return ps
    return None


def call(prompt, model, extra_env):
    wd = tempfile.mkdtemp(prefix="k8s_fc_")
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    env.update(extra_env)
    t0 = time.time()
    p = subprocess.run(["claude", "-p", "--model", model, "--tools", "", "--strict-mcp-config", "--setting-sources",
                        "project,local", "--no-session-persistence", "--output-format", "json"],
                       input=prompt, capture_output=True, text=True, cwd=wd, env=env, timeout=600)
    os.rmdir(wd)
    try:
        res = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"error": f"no json (exit {p.returncode}): {p.stdout[-300:]} {p.stderr[-300:]}"}, time.time() - t0
    return res, time.time() - t0


def limited(res):
    txt = (res.get("result") or "").lower()
    return res.get("api_error_status") == 429 or any(s in txt for s in ("usage limit", "rate limit", "session limit"))


def one(it):
    model, extra = AGENT[it["cond"]]
    tries = []
    for attempt in range(2):
        while True:
            res, secs = call(it["prompt"], model, extra)
            if "error" not in res and limited(res):
                print(time.strftime("%H:%M:%S"), "usage limit; waiting 20 min", flush=True)
                time.sleep(1200)
                continue
            break
        cost = res.get("total_cost_usd") or 0.0
        mids = sorted((res.get("modelUsage") or {}).keys())
        with LOCK:
            with open(SPEND, "a") as f:
                f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "ws": "K8S", "phase": "probe",
                                    "what": f"forecaster {it['cond']}", "id": it["id"], "model": mids, "usd": cost}) + "\n")
        ps = parse(res.get("result")) if "error" not in res else None
        tries.append({"cost": cost, "secs": round(secs, 1), "models": mids, "raw": (res.get("result") or res.get("error") or "")[:1500],
                      "usage": res.get("usage", {}).get("output_tokens_details")})
        if ps:
            return {"id": it["id"], "cond": it["cond"], "p": ps, "abstain": False, "tries": tries}
    return {"id": it["id"], "cond": it["cond"], "p": {k: 0.5 for k in QKEYS}, "abstain": True, "tries": tries}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conds", nargs="*", default=["H0", "H1", "S1"])
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    done = set()
    if os.path.exists(OUT):
        done = {(json.loads(l)["id"], json.loads(l)["cond"]) for l in open(OUT)}
    items = [json.loads(l) for l in open(os.path.join(HERE, "data", "items.jsonl"))]
    items = [it for it in items if it["cond"] in a.conds and (it["id"], it["cond"]) not in done
             and (not a.only or it["id"] in a.only)]
    print(f"{len(items)} calls", flush=True)
    with cf.ThreadPoolExecutor(a.parallel) as ex:
        for rec in ex.map(one, items):
            with LOCK:
                with open(OUT, "a") as f:
                    f.write(json.dumps(rec) + "\n")
            print(time.strftime("%H:%M:%S"), rec["id"], rec["cond"], "abstain" if rec["abstain"] else "ok",
                  round(sum(t["cost"] for t in rec["tries"]), 4), flush=True)


if __name__ == "__main__":
    main()
