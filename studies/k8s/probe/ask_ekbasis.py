"""WS-K8S Phase 0: ask Ekbasis (E0, E1) — one request per item, all seven questions, ONE request at a time (shared Mac
server). /health before each request; on failure wait 60 s and retry, at most 30 times. Resumable.
    python3 ask_ekbasis.py [--url http://mac-host:8000]   -> data/answers_ekbasis.jsonl"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.environ.get("CLAUDE_JOB_DIR", "<job>"), "tmp",
                                "ekbasis_venv", "lib", "python3.9", "site-packages"))
from ekbasis.client import Ekbasis  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://mac-host:8000")
    ap.add_argument("--conds", nargs="*", default=["E0", "E1"])
    a = ap.parse_args()
    cli = Ekbasis(url=a.url, timeout=600)
    out_path = os.path.join(HERE, "data", "answers_ekbasis.jsonl")
    done = set()
    if os.path.exists(out_path):
        done = {(json.loads(l)["id"], json.loads(l)["cond"]) for l in open(out_path)}
    items = [json.loads(l) for l in open(os.path.join(HERE, "data", "items.jsonl"))]
    items = [it for it in items if it["cond"] in a.conds and (it["id"], it["cond"]) not in done]
    print(f"{len(items)} requests to send", flush=True)
    for it in items:
        rec = None
        for attempt in range(31):
            try:
                h = cli.health()
                t0 = time.time()
                ans = cli.ask(it["state"], it["questions"])
                rec = {"id": it["id"], "cond": it["cond"], "ms": round(1000 * (time.time() - t0)), "model": h.get("model"),
                       "server_version": h.get("version"), "attempts": attempt + 1,
                       "answers": {k: {"value": v.value, "p_yes": v.p_yes, "confidence": v.confidence} for k, v in ans.items()}}
                break
            except Exception as e:  # noqa: BLE001
                print(f"{it['id']} {it['cond']} attempt {attempt + 1}: {e}", flush=True)
                time.sleep(60)
        if rec is None:
            rec = {"id": it["id"], "cond": it["cond"], "error": "server unavailable after 31 attempts"}
        with open(out_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(it["id"], it["cond"], rec.get("ms"), "ms", flush=True)


if __name__ == "__main__":
    main()
