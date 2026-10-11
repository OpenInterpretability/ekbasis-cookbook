"""Asks Ekbasis the three questions about each scenario of a split, one request at a time (concurrency 1; on HTTP 429 or a
busy server it waits and tries again). python calls.py dev|test [tag] -> answers_<split>[_tag].jsonl"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

from common import QUESTIONS, build_state, dump
from scenarios import SCENARIOS

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("EKBASIS_URL", "https://openinterp.org/api/v1")
if not os.environ.get("EKBASIS_API_KEY"):
    with open(os.path.expanduser("~/.config/ekbasis/study_api_key")) as fh:
        os.environ["EKBASIS_API_KEY"] = fh.read().strip()

from ekbasis import Ekbasis  # noqa: E402
from ekbasis.client import CannotJudge  # noqa: E402


def ask(client, state):
    for attempt in range(40):
        try:
            return client.ask(state, QUESTIONS)
        except CannotJudge as e:
            msg = str(e)
            busy = "429" in msg or "503" in msg or "did not answer" in msg or "502" in msg
            if not busy or attempt == 39:
                raise
            time.sleep(min(120, 15 * (attempt + 1)))


def main():
    split = sys.argv[1]
    tag = ("_" + sys.argv[2]) if len(sys.argv) > 2 else ""
    ids = json.load(open(os.path.join(HERE, "split.json")))[split]
    facts = {json.loads(l)["id"]: json.loads(l)["facts"] for l in open(os.path.join(HERE, "facts.jsonl"))}
    items = {s["id"]: s for s in SCENARIOS}
    out_path = os.path.join(HERE, f"answers_{split}{tag}.jsonl")
    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["id"] for l in open(out_path)}
    client = Ekbasis(surface="vert-sql-pilot")
    with open(out_path, "a") as out:
        for i in ids:
            if i in done:
                continue
            state, shown = build_state(items[i], facts[i])
            t0 = time.time()
            ans = ask(client, state)
            rec = {"id": i, "p": {k: a.p_yes for k, a in ans.items()}, "seconds": round(time.time() - t0, 2),
                   "state_sha256": hashlib.sha256(state.encode()).hexdigest(), "state_chars": len(state),
                   "request_id": client.last_request_id}
            out.write(dump(rec) + "\n")
            out.flush()
            print(i, {k: round(v, 3) for k, v in rec["p"].items()}, rec["seconds"], flush=True)


if __name__ == "__main__":
    main()
