"""Development check of the hook (no agent): what the chain guard decides for `bash pipeline.sh` on fresh databases.
    python3 hooktest.py <task ids...>"""
import json, os, subprocess, sys, tempfile
import pg, tasks as T
for tid in sys.argv[1:]:
    t = [x for x in T.TASKS if x["id"] == tid][0]
    run = tempfile.mkdtemp(prefix="hooktest-"); cwd = os.path.join(run, "cwd"); os.makedirs(cwd)
    db = "hk_" + tid.split("_")[0].lower(); pg.fresh(db)
    if t["setup"]:
        pg.psql(db, t["setup"])
    open(os.path.join(cwd, "pipeline.sh"), "w").write(t["pipeline_text"])
    cfg = {"cond": "chain_ekb", "run": run, "cwd": cwd, "request": t["request"], "rid": "x", "db": db}
    json.dump(cfg, open(os.path.join(run, "cfg.json"), "w"))
    p = subprocess.run(["python3", "guard.py", os.path.join(run, "cfg.json")], capture_output=True, text=True, timeout=900,
                       input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "bash pipeline.sh"}}))
    o = json.loads(p.stdout)["hookSpecificOutput"]
    g = [json.loads(l) for l in open(os.path.join(run, "guard_log.jsonl"))][-1]
    print(f"{tid:26s} {g['decision']:12s} at={g.get('split_at')} | " +
          " ".join(f"{pr['step']}:{max(pr['probs'].values()):.2f}/{pr['conf']:.2f}" for pr in g.get("prefixes", []) if pr["probs"])
          + "  extra: " + str({k: round(v, 2) for k, v in (next((pr["probs"] for pr in g.get("prefixes", []) if pr["step"] == t["main_pos"]), {}) or {}).items()}))
    pg.drop(db)
