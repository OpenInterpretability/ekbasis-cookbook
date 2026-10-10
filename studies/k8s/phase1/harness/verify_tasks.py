"""WS-K8S Phase 1 task verification (SPEC_agents.md §2, freeze 2): on the real cluster, every harm task's scripted harm
path must end in harm and its safe path in success without harm; the intent script must answer the ask_always question of
the harm path's critical command with a concern and every mutating command of the safe path with the default; controls:
the safe path ends in success.
    python3 verify_tasks.py [--only ID ...] [--parallel 3]   -> ../tasks/verify/<id>.json, summary on stdout"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import shutil
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_agent as RA  # noqa: E402
import guard_lib as GL  # noqa: E402
import state as S  # noqa: E402
import kube  # noqa: E402
import k8s_tasks as T  # noqa: E402

OUT = os.path.join(HERE, "..", "tasks", "verify")
LOCK = threading.Lock()


def always_question(cmd, cwd):
    calls, _loop, _b = GL.parse_line(cmd)
    mut = [c for c in calls if c["mutating"] and not any(v != "none" for v in c["flags"].get("--dry-run", []))]
    if not mut:
        return None
    c = mut[0]
    files = GL.read_files(c, cwd)
    summary = S.summarize(GL.target_namespaces(c, files), files)
    return GL.user_question(c["text"], S.facts_text(summary))


def run_path(task, which, sfx):
    work = os.path.join(kube.K8S_TMP, "verify", f"{task['id']}_{which}_{sfx}")
    spec, before, mon, rec = None, {"pvs": []}, None, {"path": which, "sfx": sfx, "steps": []}
    try:
        spec, files, before, rs0 = RA.setup(task, sfx, work)
        ns = spec["namespaces"][0]
        mon = RA.Monitor(ns, task["watched"])
        mon.start()
        time.sleep(2)
        path = task["harm_path"] if which == "harm" else task["safe_path"]
        for i, raw in enumerate(path):
            if raw.startswith("sleep "):
                time.sleep(float(raw.split()[1]))
                rec["steps"].append({"i": i, "sleep": raw})
                continue
            cmd = RA.resolve(raw.replace("@SFX@", sfx), ns, rs0)
            q = always_question(cmd, work)
            step = {"i": i, "cmd": cmd}
            if q is not None:
                ans, concern = T.respond(task, q)
                step.update({"concern": concern, "answer": ans, "question_chars": len(q)})
                if (which == "harm" and i == task["critical"]) or which == "safe":
                    step["question"] = q
            rc, out, err, secs = kube.run_shell(cmd, cwd=work, timeout=200)
            step.update({"exit": rc, "stdout": out[-600:], "stderr": err[-600:], "secs": secs})
            rec["steps"].append(step)
            time.sleep(3)
        time.sleep(RA.SETTLE)
        mon.stop()
        msum = mon.summary()
        rec["monitor"] = msum
        rec["judge"] = RA.judge(task, ns, before, msum)
    except Exception as e:  # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["trace"] = traceback.format_exc()[-1500:]
    finally:
        if mon and mon.is_alive():
            mon.stop()
        if spec:
            try:
                RA.teardown(spec, before)
            except Exception as e:  # noqa: BLE001
                rec["teardown_error"] = repr(e)
        shutil.rmtree(work, ignore_errors=True)
    return rec


def verify(task):
    sfx = hashlib.sha256(f"verify|{task['id']}".encode()).hexdigest()[:4]
    res = {"id": task["id"], "kind": task["kind"], "paths": {}}
    checks = []
    if task["kind"] == "harm":
        h = run_path(task, "harm", sfx)
        res["paths"]["harm"] = h
        crit = next((s for s in h.get("steps", []) if s.get("i") == task["critical"]), {})
        checks.append(("harm path ends in harm", bool(h.get("judge", {}).get("harm"))))
        checks.append(("intent concern on the critical command", bool(crit.get("concern"))))
    sfx2 = hashlib.sha256(f"verify-safe|{task['id']}".encode()).hexdigest()[:4]
    s = run_path(task, "safe", sfx2)
    res["paths"]["safe"] = s
    j = s.get("judge", {})
    checks.append(("safe path: success without harm", bool(j.get("success")) and not j.get("harm")))
    checks.append(("intent default on every safe-path command",
                   all(not st.get("concern") for st in s.get("steps", []) if "concern" in st)))
    res["checks"] = [{"check": c, "ok": ok} for c, ok in checks]
    res["pass"] = all(ok for _, ok in checks)
    os.makedirs(OUT, exist_ok=True)
    json.dump(res, open(os.path.join(OUT, f"{task['id']}.json"), "w"), indent=1)
    with LOCK:
        print(time.strftime("%H:%M:%S"), task["id"], "PASS" if res["pass"] else "FAIL",
              "; ".join(f"{c}={'ok' if ok else 'NO'}" for c, ok in checks), flush=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--parallel", type=int, default=3)
    a = ap.parse_args()
    kube.check_context()
    RA.clean_nodes()
    tasks = [t for t in T.TASKS if not a.only or t["id"] in a.only]
    for t in [t for t in tasks if t["node_exclusive"]]:
        verify(t)
    rest = [t for t in tasks if not t["node_exclusive"]]
    with cf.ThreadPoolExecutor(a.parallel) as ex:
        list(ex.map(verify, rest))
    RA.clean_nodes()


if __name__ == "__main__":
    main()
