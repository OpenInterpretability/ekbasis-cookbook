"""Step 6: one Ekbasis request per labeled PR, concurrency 1 (PREREG §5). Resumable: answers already written are kept.

usage: run_ekbasis.py dev|test
The key is read from ~/.config/ekbasis/study_api_key and never printed or written.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))  # ekbasis 0.1.16 from PyPI
from ekbasis import Ekbasis  # noqa: E402
from ekbasis.client import CannotJudge  # noqa: E402

from ghc import ROOT  # noqa: E402
from state import QUESTIONS, build_state  # noqa: E402


def main(split):
    key = open(os.path.expanduser("~/.config/ekbasis/study_api_key")).read().strip()
    c = Ekbasis(url="https://openinterp.org/api/v1", api_key=key, timeout=180, surface="study-deps")
    cands = {f"{x['repo']}#{x['number']}": x for x in map(json.loads, open(os.path.join(ROOT, "data", f"{split}_candidates.jsonl")))}
    labels = [json.loads(l) for l in open(os.path.join(ROOT, "data", f"{split}_labels.jsonl"))]
    facts = {}
    for l in open(os.path.join(ROOT, "data", f"{split}_facts.jsonl")):
        d = json.loads(l)
        facts[d["id"]] = d["facts"]
    out_p = os.path.join(ROOT, "data", f"{split}_answers.jsonl")
    done = set()
    if os.path.exists(out_p):
        done = {json.loads(l)["id"] for l in open(out_p)}
    todo = [f"{l['repo']}#{l['number']}" for l in labels if l["label"] is not None]
    todo = [i for i in todo if i not in done and i in facts and "error" not in facts[i]]
    print(split, len(todo), "to ask", flush=True)
    with open(out_p, "a") as f:
        for k, i in enumerate(todo):
            state = build_state(cands[i], facts[i])
            for attempt in range(12):
                t0 = time.time()
                try:
                    ans = c.ask(state, QUESTIONS)
                    break
                except CannotJudge as e:
                    msg = str(e)
                    wait = 30 * (attempt + 1) if ("429" in msg or "503" in msg or "502" in msg or "did not answer" in msg) else 10
                    print(f"  retry {i} in {wait}s ({msg[:80]})", flush=True)
                    time.sleep(wait)
            else:
                f.write(json.dumps({"id": i, "error": "no answer after 12 attempts"}) + "\n")
                continue
            rec = {"id": i, "p_api": ans["api"].p_yes, "p_other": ans["other"].p_yes, "p_any": ans["any"].p_yes,
                   "latency_s": round(time.time() - t0, 2), "timing": c.last_timing, "usage": c.last_usage,
                   "request_id": c.last_request_id, "state_chars": len(state)}
            f.write(json.dumps(rec) + "\n")
            f.flush()
            if k % 20 == 0:
                print(k, i, rec["p_api"], rec["p_other"], rec["p_any"], rec["latency_s"], flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
