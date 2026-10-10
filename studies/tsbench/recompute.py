"""Recomputes every table of this study from the released answers and a fresh download of TS-Bench.

    pip install numpy scikit-learn
    python recompute.py            # about 2 minutes; writes recompute_output.txt

Steps:
1. Checks the files in frozen/ against the last SHA-256 recorded for them in frozen/PREREG_sha256.txt.
2. Downloads the 9 TS-Bench test files from the ToolSafe repository at the pinned commit (Git LFS) and checks the
   data hash registered in PREREG.md. The benchmark's text is not redistributed here.
3. Rebuilds the Ekbasis requests with the frozen converter and checks that they hash exactly like the ones that ran
   (items.jsonl), then rebuilds the memorization variants the same way (variants_items.jsonl).
4. Joins answers.jsonl and variant_answers.jsonl (id, subset, label, P(yes) only) back to the items and runs the
   frozen analysis scripts unchanged: the registered analysis, the recalibration (refitting the calibrator first and
   checking it matches the frozen one), the leakage checks and the memorization test.

Not reproducible from the released files: the 3-level exploratory question (its answers are not released, so
"level exact acc" prints None) and the per-call tokens and latencies.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import runpy
import shutil
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = os.path.join(HERE, "frozen")
COMMIT = "46358fa424a927a895c6c8322f99032c4eb5155e"
REPO_MEDIA = f"https://media.githubusercontent.com/media/MurrayTom/ToolSafe/{COMMIT}/"
DATA_SHA = "e67381ea236cd2d3c6274dff0a6128ebc9598f44eba5ce0e719eaec89113fed7"
FILES = ["agentharm-traj/benign_steps.json", "agentharm-traj/harmful_steps.json",
         "asb-traj/test/DPI_attack_success.json", "asb-traj/test/OPI_attack_success.json",
         "asb-traj/test/atttack_failure.json", "agentdojo-traj/workspace.json", "agentdojo-traj/travel.json",
         "agentdojo-traj/slack.json", "agentdojo-traj/banking.json"]


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def recorded_hashes():
    last = {}
    for line in open(os.path.join(FROZEN, "PREREG_sha256.txt")):
        m = re.match(r"([0-9a-f]{64})  (\S+)", line)
        if m:
            last[m.group(2)] = m.group(1)
    return last


def main():
    log = io.StringIO()

    def say(*a):
        print(*a)
        print(*a, file=log)

    rec = recorded_hashes()
    for name in sorted(os.listdir(FROZEN)):
        if name in rec:
            ok = sha(os.path.join(FROZEN, name)) == rec[name]
            say(f"frozen/{name}: {'matches' if ok else 'DIFFERS FROM'} the recorded SHA-256")
            assert ok, name

    work = tempfile.mkdtemp(prefix="tsbench_")
    for name in os.listdir(FROZEN):
        shutil.copy(os.path.join(FROZEN, name), work)
    data = os.path.join(work, "ToolSafe", "TS-Bench")
    for rel in FILES:
        os.makedirs(os.path.dirname(os.path.join(data, rel)), exist_ok=True)
        cache = os.path.join(HERE, ".tsbench_cache", rel)
        if not os.path.exists(cache):
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            urllib.request.urlretrieve(REPO_MEDIA + "TS-Bench/" + rel, cache)
        shutil.copy(cache, os.path.join(data, rel))
    got = hashlib.sha256(b"".join(open(os.path.join(data, r), "rb").read() for r in FILES)).hexdigest()
    say(f"TS-Bench data SHA-256 {'matches' if got == DATA_SHA else 'DIFFERS'} ({got})")
    assert got == DATA_SHA

    os.chdir(work)
    sys.path.insert(0, work)
    with contextlib.redirect_stdout(io.StringIO()):
        runpy.run_path("convert_tsbench.py", run_name="__main__")
        runpy.run_path("variants.py", run_name="__main__")
    for name in ("items.jsonl", "variants_items.jsonl"):
        ok = sha(name) == rec[name]
        say(f"rebuilt {name}: {'identical to' if ok else 'DIFFERENT FROM'} the requests that ran")
        assert ok

    items = {it["id"]: it for it in map(json.loads, open("items.jsonl"))}
    with open("FULL_answers.jsonl", "w") as f:
        for a in map(json.loads, open(os.path.join(HERE, "answers.jsonl"))):
            it = items[a["id"]]
            assert it["label"] == a["label"] and it["subset"] == a["subset"]
            f.write(json.dumps({"id": a["id"], "subset": a["subset"], "cluster": it["cluster"], "label": a["label"],
                                "p_unsafe": a["p_unsafe"], "error": None, "ms": 0}) + "\n")
    injected = {(v["id"], v["cond"]): v["injected"] for v in map(json.loads, open("variants_items.jsonl"))}
    with open("VAR_answers.jsonl", "w") as f:
        for a in map(json.loads, open(os.path.join(HERE, "variant_answers.jsonl"))):
            f.write(json.dumps({"id": a["id"], "cond": a["cond"], "injected": injected[(a["id"], a["cond"])],
                                "p_unsafe": a["p_unsafe"], "error": None}) + "\n")

    frozen_cal = json.load(open("calibrator.json"))
    with contextlib.redirect_stdout(io.StringIO()):
        runpy.run_path("calibrate.py", run_name="__main__")
    refit = json.load(open("calibrator.json"))
    same = (abs(refit["primary_platt"]["a"] - frozen_cal["primary_platt"]["a"]) < 1e-4
            and abs(refit["primary_platt"]["b"] - frozen_cal["primary_platt"]["b"]) < 1e-4
            and abs(refit["primary_platt"]["threshold"] - frozen_cal["primary_platt"]["threshold"]) < 1e-4
            and abs(refit["secondary_isotonic"]["threshold"] - frozen_cal["secondary_isotonic"]["threshold"]) < 1e-4)
    say(f"calibrator refitted from the released answers: {'matches' if same else 'DIFFERS FROM'} the frozen one")
    shutil.copy(os.path.join(FROZEN, "calibrator.json"), "calibrator.json")

    for title, script in [("Registered analysis (threshold 0.5)", "recompute.py"),
                          ("Addendum 3: recalibration tested on AgentDojo", "recal_eval.py"),
                          ("Leakage check (exploratory)", "leak_check.py"),
                          ("Leakage check: the agent's own thought (exploratory)", "leak_check_thought.py"),
                          ("Addendum 4: memorization test", "variants_eval.py")]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            runpy.run_path(script, run_name="__main__")
        say(f"\n##### {title} ({script})\n{buf.getvalue().rstrip()}")

    os.chdir(HERE)
    open(os.path.join(HERE, "recompute_output.txt"), "w").write(log.getvalue())
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
