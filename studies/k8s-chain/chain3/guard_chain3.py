#!/usr/bin/env python3
"""WS-K8S chain study v3: the same chain guard (../chain/guard_chain.py, "look when unsure" over a pipeline), with the
forecaster as the arm. chain_ekb: Ekbasis (the production API, Skopos-free release, the Phase 1 prompts and questions);
chain_glm: GLM-5.3-Flash, a large general LLM we serve (OpenAI-compatible endpoint, the Phase 1 LLM prompt that the
Sonnet forecaster used, default reasoning, temperature 0, at most 4,000 output tokens, streaming). Everything else is
identical. Every forecaster call is metered in <run>/forecast_calls.jsonl: engine, seconds, prompt tokens, generated
tokens (reasoning included), whether a usable answer came back."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "chain"))
import guard_chain as GC  # noqa: E402

GL, P, R = GC.GL, GC.GL.P, GC.GL.R
GLM_URL = os.environ["GLM_URL"]  # an OpenAI-compatible chat completions URL serving GLM-5.3-Flash
EKB_URL = os.environ.get("EKBASIS_URL", "https://openinterp.org/api/v1").rstrip("/") + "/v1/systemone"


def meter(cfg, rec):
    with open(os.path.join(cfg["run"], "forecast_calls.jsonl"), "a") as f:
        f.write(json.dumps({"t": time.time(), **rec}) + "\n")


def forecast_ekb(cfg, wtext, qs, rule_ids):
    """What Phase 1's forecast_ekbasis sends (state + questions, rules recapped), metered from the API's usage."""
    qs2 = P.recap_all(qs, R.rule_texts(rule_ids)) if rule_ids else qs
    body = json.dumps({"state": wtext, "questions": qs2}).encode()
    key = os.environ["EKBASIS_API_KEY"]
    last = None
    for attempt in range(4):
        t0 = time.time()
        try:
            req = urllib.request.Request(EKB_URL, body, {"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                                                         "User-Agent": "ekbasis-k8s-chain3/1.0"})
            with urllib.request.urlopen(req, timeout=600) as r:
                d = json.loads(r.read())
            ms = round(1000 * (time.time() - t0))
            probs = {k: float(a.get("probability", a.get("noul"))) for k, a in d["answers"].items()}
            u = d.get("usage") or {}
            meter(cfg, {"engine": "ekbasis", "ms": ms, "in": u.get("input_tokens"), "out": 0, "ok": True, "attempt": attempt})
            return probs, {"ms": ms, "in": u.get("input_tokens"), "out": 0}
        except Exception as e:  # noqa: BLE001
            last = repr(e)[:200]
            time.sleep(10)
    meter(cfg, {"engine": "ekbasis", "ms": None, "ok": False, "error": last})
    raise GL.ForecasterError(f"ekbasis: {last}")


def forecast_glm(cfg, wtext, qs, rule_ids):
    prompt = GL._llm_prompt(wtext, qs)
    key = os.environ["GLM_API_KEY"]
    body = {"model": "glm-5.3-flash", "temperature": 0, "max_tokens": 4000, "stream": True,
            "stream_options": {"include_usage": True}, "messages": [{"role": "user", "content": prompt}]}
    t0, last, tot_in, tot_out = time.time(), None, 0, 0
    for attempt in range(2):
        txt, u = "", {}
        try:
            req = urllib.request.Request(GLM_URL, json.dumps(body).encode(), {"Authorization": f"Bearer {key}",
                                                                              "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:") or line == "data: [DONE]":
                        continue
                    ev = json.loads(line[5:])
                    u = ev.get("usage") or u
                    for ch in ev.get("choices") or []:
                        txt += (ch.get("delta") or {}).get("content") or ""
        except Exception as e:  # noqa: BLE001  infrastructure: retried, never counted as an answer
            last = f"infra: {repr(e)[:150]}"
            continue
        tot_in += u.get("prompt_tokens") or 0
        tot_out += u.get("completion_tokens") or 0
        ps = GL._parse_probs(txt, list(qs))
        if ps:
            ms = round(1000 * (time.time() - t0))
            meter(cfg, {"engine": "glm", "ms": ms, "in": tot_in, "out": tot_out, "ok": True, "attempt": attempt})
            return ps, {"ms": ms, "in": tot_in, "out": tot_out}
        last = "unparsable: " + txt[-120:].replace("\n", " ")
    meter(cfg, {"engine": "glm", "ms": round(1000 * (time.time() - t0)), "in": tot_in, "out": tot_out, "ok": False,
                "error": last})
    raise GL.ForecasterError(f"glm: {last}")


GL.forecast_ekbasis = forecast_ekb
GL.forecast_sonnet = forecast_glm
GC.ekb_cfg = lambda cfg: dict(cfg, cond="ask_ekbasis" if cfg["cond"] == "chain_ekb" else "ask_glm")

if __name__ == "__main__":
    GC.main()
