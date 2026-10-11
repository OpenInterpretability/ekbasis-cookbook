"""Baseline (b): the production GLM-5.3 as an LLM judge (NOT run yet). It shares the production GPUs, so: concurrency 1,
a pause between calls, reasoning_effort "low", and only the fixed stratified subsample data/glm_ids.txt (PREREG §5).

    GLM_BASE_URL=... GLM_API_KEY=... [GLM_MODEL=glm-5.2] .venv/bin/python run_glm.py --go

Same state text and the same three questions (with their criteria) as Ekbasis; the judge answers with probabilities in
JSON. Writes preds/glm.jsonl (resumable).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request

import statebuild as SB


def load_requests():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "requests.jsonl")
    return [json.loads(l) for l in open(p)]

ROOT = os.path.dirname(os.path.abspath(__file__))
SYSTEM = ("You forecast what a database migration will do. Read the situation, then answer each question with the "
          "probability (0 to 1) that the answer is yes. Reply with JSON only, like {\"lost\": 0.1, \"fails\": 0.7, "
          "\"half\": 0.6}.")
PAUSE_S = 2.0


def user_msg(it):
    qs = "\n".join(f"- {k}: {q['instructions']}" for k, q in it["questions"].items())
    return f"{it['state']}\n\nQuestions:\n{qs}"


def call(base, key, model, it):
    body = {"model": model, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_msg(it)}],
            "temperature": 0, "max_tokens": 2000, "reasoning_effort": "low"}
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    text = d["choices"][0]["message"].get("content") or ""
    m = re.search(r"\{[^{}]*\}", text)
    p = json.loads(m.group(0)) if m else {}
    return {f"p_{k}": float(p[k]) for k in SB.QUESTIONS if k in p}, d.get("usage", {}), text[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    if not a.go:
        sys.exit("refusing to call the model without --go (PREREG §6)")
    base, key = os.environ["GLM_BASE_URL"], os.environ["GLM_API_KEY"]
    model = os.environ.get("GLM_MODEL", "glm-5.2")
    ids = [l.strip() for l in open(os.path.join(ROOT, "data", "glm_ids.txt")) if l.strip()]
    items = {it["id"]: it for it in load_requests()}
    os.makedirs(os.path.join(ROOT, "preds"), exist_ok=True)
    out_path = os.path.join(ROOT, "preds", "glm.jsonl")
    done = {json.loads(l)["id"] for l in open(out_path)} if os.path.exists(out_path) else set()
    with open(out_path, "a") as f:
        for i in ids:
            if i in done or i not in items:
                continue
            t0 = time.time()
            try:
                p, usage, raw = call(base, key, model, items[i])
                r = {"id": i, "secs": round(time.time() - t0, 2), "usage": usage, **p, "raw": raw}
            except Exception as e:
                r = {"id": i, "error": f"{type(e).__name__}: {e}"[:300]}
            f.write(json.dumps(r) + "\n")
            f.flush()
            print(i, r.get("error") or {k: v for k, v in r.items() if k.startswith("p_")}, file=sys.stderr)
            time.sleep(PAUSE_S)


if __name__ == "__main__":
    main()
