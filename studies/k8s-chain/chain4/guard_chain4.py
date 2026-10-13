#!/usr/bin/env python3
"""WS-K8S chain study v4: the v3 guard (../chain3/guard_chain3.py: the same chain guard, Ekbasis or GLM-5.3 as the
judge) with ONE change: the prefixes of a pipeline range are forecast in parallel, in waves of WIDTH (5), for both
judges, as ekbasis.check_plan(parallel=5) does. The decision is the same as one by one: the results are read in order
and the guard stops at the first flagged or uncertain prefix (a wave past it costs at most WIDTH - 1 extra calls).

Also: every guard decision that ran past the policy records guard_ms, the wall-clock time of that hook call (v3 left it
out of the fail-closed decisions, most of them GLM failures)."""
from __future__ import annotations

import concurrent.futures as cf
import os
import sys
import time

T_START = time.time()   # the hook is one process per tool call: this is the call's start
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "chain3"))
import guard_chain3 as G3  # noqa: E402  (patches the forecasters, as in v3)

GC, GL, S = G3.GC, G3.GL, G3.GC.S
WIDTH = int(os.environ.get("CHAIN_WIDTH", "5"))
_log = GC.log
NO_JUDGE = {"policy_deny", "wait"}


def log(cfg, rec):
    if rec.get("decision") not in NO_JUDGE and "guard_ms" not in rec:
        rec["guard_ms"] = round(1000 * (time.time() - T_START))
    rec.setdefault("width", WIDTH)
    _log(cfg, rec)


def chain(cfg, cmd, a, calls, rec, t0):
    """v3's chain() with the prefixes forecast in parallel waves; same decisions, same messages."""
    files_list = [GL.read_files(c, cfg["cwd"]) for c in calls]
    namespaces = sorted({n for c, f in zip(calls, files_list) for n in GL.target_namespaces(c, f)})
    merged = {}
    for f in files_list:
        merged.update(f)
    summary = S.summarize(namespaces, merged)
    rec.update({"namespaces": namespaces, "steps": [c["step"] for c in calls], "prefixes": [], "ekb_calls": 0})

    def one(i):
        seq = calls[:i]
        sentences, ov = GL.code_checks(seq, cfg["cwd"])
        try:
            probs, meta = GL.forecast(GC.ekb_cfg(cfg), summary, [c["text"] for c in seq], files_list[:i], cfg["request"],
                                      sentences, ov)
            return seq, sentences, probs, meta, None
        except GL.ForecasterError as e:
            return seq, sentences, None, {}, str(e)

    n = len(calls)
    with cf.ThreadPoolExecutor(WIDTH) as ex:
        for start in range(1, n + 1, WIDTH):
            wave = list(range(start, min(n, start + WIDTH - 1) + 1))
            results = list(ex.map(one, wave))
            for i, (seq, sentences, probs, meta, err) in zip(wave, results):
                rec["ekb_calls"] += 1
                if err:
                    rec["forecaster_error"] = err
                if probs is None:
                    conf, flags = 0.0, ["forecaster_error"]
                else:
                    conf = GC.confidence(meta.get("raw") or probs)
                    flags = [k for k in GL.GENERIC_HARMFUL + list(GL.INTENT) if probs.get(k, 0) >= GC.HARM_AT]
                rec["prefixes"].append({"step": seq[-1]["step"], "probs": probs, "conf": round(conf, 4), "flags": flags,
                                        "code_checks": sentences, "ms": meta.get("ms")})
                if flags or conf < GC.LOOK_BELOW:
                    k = seq[-1]["step"]
                    why = "flags" if flags else "is unsure about"
                    if i == 1:
                        rec.update({"decision": "split_single", "split_at": k, "why": why,
                                    "guard_ms": round(1000 * (time.time() - t0))})
                        log(cfg, rec)
                        GC.out("deny", GC.MSG_SINGLE.format(k=k))
                    rec.update({"decision": "split", "split_at": k, "run_first": [a, calls[i - 2]["step"]], "why": why,
                                "guard_ms": round(1000 * (time.time() - t0))})
                    log(cfg, rec)
                    GC.out("deny", GC.MSG_SPLIT.format(a=a, p=k - 1, k=k, why=why))
    rec.update({"decision": "allow_batch", "guard_ms": round(1000 * (time.time() - t0))})
    log(cfg, rec)
    GC.out("allow")


GC.log = log
GC.chain = chain

if __name__ == "__main__":
    GC.main()
