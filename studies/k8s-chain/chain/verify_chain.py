"""Verifies the chain study's tasks on the cluster (before any agent run): a harm task's pipeline, run as given, ends in
harm, and Phase 1's safe path ends in success without harm; a control's pipeline ends in success without harm.
    python3 verify_chain.py [--only ID ...]   -> verify/<id>.json, summary on stdout"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "phase1", "harness"))
import chain_tasks as CT  # noqa: E402
import run_agent as RA  # noqa: E402
import kube  # noqa: E402

OUT = os.path.join(HERE, "verify")


def run_path(task, path, tag):
    sfx = f"v{abs(hash((task['id'], tag, time.time()))) % 0xfff:03x}"
    run = os.path.join(kube.K8S_TMP, "chainverify", f"{task['id']}_{tag}")
    os.makedirs(run, exist_ok=True)
    cwd = os.path.join(run, "cwd")
    spec, before, mon = None, {"pvs": []}, None
    try:
        spec, files, before, rs0 = RA.setup(task, sfx, cwd)
        ns = spec["namespaces"][0]
        mon = RA.Monitor(ns, task["watched"])
        mon.start()
        env = dict(os.environ, KUBECONFIG=kube.KUBECONFIG, PATH=os.path.dirname(kube.KUBECTL) + ":" + os.environ["PATH"])
        outs = []
        for cmd in path:
            cmd = RA.resolve(cmd.replace("@SFX@", sfx), ns, rs0)
            p = subprocess.run(["bash", "-c", cmd], cwd=cwd, env=env, capture_output=True, text=True, timeout=600)
            outs.append({"cmd": cmd, "rc": p.returncode, "out": (p.stdout + p.stderr)[-600:]})
        time.sleep(RA.SETTLE)
        mon.stop()
        res = RA.judge(task, ns, before, mon.summary())
        return {"ok": True, "harm": res["harm"], "success": res["success"], "detail": res.get("detail"), "cmds": outs}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": repr(e)}
    finally:
        if mon and mon.is_alive():
            mon.stop()
        if spec:
            RA.teardown(spec, before)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    kube.check_context()
    os.makedirs(OUT, exist_ok=True)
    bad = 0
    for t in CT.TASKS:
        if a.only and t["id"] not in a.only:
            continue
        rec = {"id": t["id"], "kind": t["kind"]}
        if t["kind"] == "harm":
            rec["pipeline"] = run_path(t, ["bash pipeline.sh"], "pipe")
            rec["safe"] = run_path(t, t["orig_safe_path"], "safe")
            ok = rec["pipeline"].get("harm") is True and rec["safe"].get("success") is True and rec["safe"].get("harm") is False
        else:
            rec["pipeline"] = run_path(t, ["bash pipeline.sh"], "pipe")
            ok = rec["pipeline"].get("success") is True and rec["pipeline"].get("harm") is False
        rec["pass"] = ok
        bad += not ok
        json.dump(rec, open(os.path.join(OUT, t["id"] + ".json"), "w"), indent=1)
        print(time.strftime("%H:%M:%S"), t["id"], "PASS" if ok else "FAIL",
              {k: {x: rec[k].get(x) for x in ("harm", "success", "error")} for k in ("pipeline", "safe") if k in rec},
              flush=True)
    print("failures:", bad)


if __name__ == "__main__":
    main()
