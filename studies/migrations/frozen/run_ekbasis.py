"""Model run (NOT run yet: wait for the lead's go). One request per item: the frozen state and the frozen questions.

    .venv/bin/python run_ekbasis.py --go [--pilot 20] [--concurrency 1] [--per-statement]

Key: ~/.config/ekbasis/study_api_key (read here, never printed). Endpoint: https://openinterp.org/api/v1.
Writes preds/ekbasis.jsonl (resumable: items already answered are skipped). --pilot N runs the first N items of
data/pilot_ids.txt only (fixed list, PREREG §6).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import urllib.error
import urllib.request

from ekbasis.client import USER_AGENT, Answer

import statebuild as SB


def load_requests():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "requests.jsonl")
    return [json.loads(l) for l in open(p)]

URL = "https://openinterp.org/api/v1"
KEY_PATH = os.path.expanduser("~/.config/ekbasis/study_api_key")
MAX_TOKENS = 32000
ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="required: actually call the API")
    ap.add_argument("--pilot", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--per-statement", action="store_true", help="also ask the exploratory per-statement questions")
    a = ap.parse_args()
    if not a.go:
        sys.exit("refusing to call the model without --go (PREREG §6: wait for the lead's signal)")
    key = open(KEY_PATH).read().strip()

    def post(state, qs):
        """The client's request (POST /v1/systemone), keeping the response headers: Server-Timing separates the
        gateway queue from the model time, and the other study shares the queue."""
        req = urllib.request.Request(f"{URL}/v1/systemone", data=json.dumps({"state": state, "questions": qs}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": USER_AGENT,
                                              "Authorization": f"Bearer {key}", "X-Ekbasis-Surface": "pr-study"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read())
            return d, r.headers.get("Server-Timing"), r.headers.get("X-Ekbasis-Request-Id")
    items = load_requests()
    if a.pilot:
        ids = [l.strip() for l in open(os.path.join(ROOT, "data", "pilot_ids.txt")) if l.strip()][:a.pilot]
        items = [it for it in items if it["id"] in set(ids)]
    os.makedirs(os.path.join(ROOT, "preds"), exist_ok=True)
    out_path = os.path.join(ROOT, "preds", "ekbasis.jsonl")
    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["id"] for l in open(out_path)}
    todo = [it for it in items if it["id"] not in done]
    print(f"{len(todo)} items to ask ({len(done)} already answered)", file=sys.stderr)

    def ask(it):
        qs = dict(it["questions"])
        if a.per_statement:
            qs.update({f"f{k}": SB.sql_fails(k) for k in range(1, it["n_statements"] + 1)})
        if it["est_tokens"] > MAX_TOKENS:
            return {"id": it["id"], "error": "too long"}
        err = None
        for attempt in range(3):
            t0 = time.time()
            try:
                d, timing, rid = post(it["state"], qs)
                ans = {k: Answer.from_api(v) for k, v in d["answers"].items()}
                return {"id": it["id"], "secs": round(time.time() - t0, 2), "server_timing": timing, "request_id": rid,
                        "usage": d.get("usage"), **{f"p_{k}": v.p_yes for k, v in ans.items()}}
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"
            except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                err = f"{type(e).__name__}: {e}"[:300]
            time.sleep(5 * (attempt + 1))
        return {"id": it["id"], "error": err}

    with open(out_path, "a") as f, ThreadPoolExecutor(a.concurrency) as ex:
        for r in ex.map(ask, todo):
            f.write(json.dumps(r) + "\n")
            f.flush()
            print(r["id"], r.get("error") or {k: round(v, 3) for k, v in r.items() if k.startswith("p_")}, file=sys.stderr)


if __name__ == "__main__":
    main()
