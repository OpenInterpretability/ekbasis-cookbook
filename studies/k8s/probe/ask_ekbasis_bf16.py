"""WS-K8S optional add-on (SPEC_agents.md §9): re-ask Phase 0's E1 items, byte-identical, on a bf16 server, to measure
what the MLX 4-bit build loses. One request at a time. Writes data/answers_ekbasis_bf16.jsonl (resumable).
    python3 ask_ekbasis_bf16.py --url http://127.0.0.1:PORT"""
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
    ap.add_argument("--url", required=True)
    ap.add_argument("--conds", nargs="*", default=["E1"])
    a = ap.parse_args()
    cli = Ekbasis(url=a.url, timeout=600)
    out = os.path.join(HERE, "data", "answers_ekbasis_bf16.jsonl")
    done = {(json.loads(l)["id"], json.loads(l)["cond"]) for l in open(out)} if os.path.exists(out) else set()
    items = [json.loads(l) for l in open(os.path.join(HERE, "data", "items.jsonl"))]
    items = [it for it in items if it["cond"] in a.conds and (it["id"], it["cond"]) not in done]
    h = cli.health()
    print(h, len(items), "requests", flush=True)
    for it in items:
        t0 = time.time()
        ans = cli.ask(it["state"], it["questions"])
        rec = {"id": it["id"], "cond": it["cond"], "ms": round(1000 * (time.time() - t0)), "model": h.get("model"),
               "server_version": h.get("version"),
               "answers": {k: {"value": v.value, "p_yes": v.p_yes, "confidence": v.confidence} for k, v in ans.items()}}
        with open(out, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(it["id"], it["cond"], rec["ms"], "ms", flush=True)


if __name__ == "__main__":
    main()
