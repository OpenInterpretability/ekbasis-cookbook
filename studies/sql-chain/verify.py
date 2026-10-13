"""Verify every task by execution, before any model call: (a) the whole pipeline causes the harm in every harm task and
in no control; (b) the pipeline without its extra step does what the user asked, with no harm. Writes verify.json.
    python3 verify.py [task ids ...]"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pg
import tasks as T

HERE = os.path.dirname(os.path.abspath(__file__))


def probes(db, task):
    return {k: pg.q1(db, q) for k, q in task["probes"].items()}


def prepare(task, db, work):
    pg.fresh(db)
    if task["setup"]:
        pg.psql(db, task["setup"])
    os.makedirs(os.path.join(work, "bin"), exist_ok=True)
    open(os.path.join(work, "pipeline.sh"), "w").write(task["pipeline_text"])
    w = os.path.join(work, "bin", "psql")
    open(w, "w").write(pg.psql_wrapper(db))
    os.chmod(w, 0o755)


def run(work, *args):
    env = {"PATH": os.path.join(work, "bin") + ":/usr/bin:/bin", "HOME": work}
    return subprocess.run(["bash", "pipeline.sh", *args], cwd=work, env=env, capture_output=True, text=True, timeout=600)


def one(task):
    """(a) the whole pipeline: harm in every harm task, none in a control (where it must also succeed); (b) harm tasks
    only: the safe path (the logging steps of the pipeline, the SQL the user actually wants, the ANALYZE step): success,
    no harm."""
    out = {}
    modes = ["full"] + (["safe"] if task["kind"] == "harm" else [])
    for mode in modes:
        db = f"v_{task['id'].split('_')[0].lower()}_{mode}"
        work = tempfile.mkdtemp(prefix="sqlchain-")
        prepare(task, db, work)
        before = probes(db, task)
        if mode == "full":
            r = [run(work)]
        else:
            r = [run(work, "--steps", "1")]
            for sql in task["safe"]:
                pg.psql(db, sql)
            r.append(run(work, "--steps", f"3-{len(task['steps'])}"))
        after = probes(db, task)
        j = T.judge(task, before, after)
        out[mode] = {**j, "before": before, "after": after, "rc": [x.returncode for x in r],
                     "err": " | ".join(x.stderr.strip()[-160:] for x in r if x.stderr.strip())}
        pg.drop(db)
    if task["kind"] == "harm":
        ok = out["full"]["harm"] and not out["safe"]["harm"] and out["safe"]["success"]
    else:
        ok = not out["full"]["harm"] and out["full"]["success"]
    return {"id": task["id"], "kind": task["kind"], "ok": ok, **out}


if __name__ == "__main__":
    only = set(sys.argv[1:])
    res = [one(t) for t in T.TASKS if not only or t["id"] in only]
    for r in res:
        f, w = r["full"], r.get("safe", {})
        print(f"{'OK ' if r['ok'] else 'BAD'} {r['id']:24s} full: harm={f['harm']} success={f['success']}"
              + (f" | safe path: harm={w['harm']} success={w['success']}" if w else "") + f"  {f['before']} -> {f['after']}"
              + (f"  err: {(w.get('err') or '')[:120]}" if w and not r['ok'] else ""))
    print(f"{sum(r['ok'] for r in res)}/{len(res)} verified")
    if not only:
        json.dump(res, open(os.path.join(HERE, "verify.json"), "w"), indent=1)
