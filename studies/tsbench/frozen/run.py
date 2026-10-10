"""Sends converted TS-Bench items to the hosted Ekbasis API and writes one answer line per item.

EKBASIS_URL=https://openinterp.org/api/v1 EKBASIS_API_KEY=... python3 run.py --pilot 30 --out pilot_answers.jsonl
--pilot N: N items, stratified evenly over the three subsets, drawn with the frozen seed (PREREG.md §6).
The key is read from the environment and never written anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ekbasis-src"))
from ekbasis.client import Answer, Ekbasis, CannotJudge  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PILOT_SEED = 7


def pilot_sample(items, n):
    rng = random.Random(PILOT_SEED)
    subsets = ["agentharm", "asb", "agentdojo"]
    per = n // len(subsets)
    out = []
    for s in subsets:
        pool = [it for it in items if it["subset"] == s]
        out += rng.sample(pool, per)
    return out


def answer(client, it, retries):
    row = {k: it[k] for k in ("id", "subset", "cluster", "label", "truncated")}
    row["state_chars"] = len(it["state"])
    row["prompt_chars"] = len(it["state"]) + len(json.dumps(it["questions"]))
    err, ans = None, None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(RETRY_WAIT_S)
        t0 = time.time()
        try:
            raw = client._call("/v1/systemone", {"state": it["state"], "questions": it["questions"]})
            ans = {k: Answer.from_api(v) for k, v in raw["answers"].items()}
            row["input_tokens"] = (raw.get("usage") or {}).get("input_tokens")
            row["server_latency_s"] = raw.get("latency_s")
            err = None
            break
        except (CannotJudge, KeyError, TypeError, ValueError) as e:
            err = f"{type(e).__name__}: {str(e)[:300]}"
    row["attempts"] = attempt + 1
    row["ms"] = round(1000 * (time.time() - t0), 1)
    row["error"] = err
    row["p_unsafe"] = ans["unsafe"].p_yes if ans else None
    row["level"] = str(ans["level"].value) if ans else None
    row["level_probs"] = ans["level"].probabilities if ans else None
    return row


RETRY_WAIT_S = 10
STOP_AT_UTC = "2026-10-11T03:30:00"   # owner's deadline: pause before the B200 profile change
MAX_TOKENS = 20_000_000               # owner's budget stop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=int, default=0)
    ap.add_argument("--full", action="store_true", help="every item (approved by the owner 2026-10-10)")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--retries", type=int, default=1)
    a = ap.parse_args()
    items = [json.loads(l) for l in open(os.path.join(HERE, "items.jsonl"))]
    if a.pilot:
        items = pilot_sample(items, a.pilot)
    elif not a.full:
        sys.exit("pass --pilot N or --full")
    # resumable: every id already written (answered or failed) is skipped; rows are appended one per item
    done, tokens = set(), 0
    if os.path.exists(a.out):
        for l in open(a.out):
            r = json.loads(l)
            done.add(r["id"])
            tokens += r.get("input_tokens") or 0
    todo = [it for it in items if it["id"] not in done]
    print(f"{len(items)} items, {len(done)} already written, {len(todo)} to run, {tokens} tokens so far", flush=True)
    client = Ekbasis(timeout=180, surface="extbench-tsbench")
    stop_at = time.mktime(time.strptime(STOP_AT_UTC, "%Y-%m-%dT%H:%M:%S")) - time.timezone
    lock = threading.Lock()
    state = {"tokens": tokens, "n": 0, "stop": None}
    with open(a.out, "a") as f:
        def work(it):
            if state["stop"]:
                return
            if time.time() >= stop_at:
                state["stop"] = "deadline 03:30 UTC"
                return
            if state["tokens"] >= MAX_TOKENS:
                state["stop"] = "token budget"
                return
            row = answer(client, it, a.retries)
            with lock:
                f.write(json.dumps(row) + "\n")
                f.flush()
                state["tokens"] += row.get("input_tokens") or 0
                state["n"] += 1
                if row["error"] or state["n"] % 100 == 0:
                    print(f"{state['n']}/{len(todo)} tokens={state['tokens']} {row['id']} "
                          f"{'ERR ' + row['error'] if row['error'] else ''}", flush=True)
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            list(ex.map(work, todo))
    print(f"finished: {state['n']} written this session, tokens={state['tokens']}, stop={state['stop']}", flush=True)


if __name__ == "__main__":
    main()
