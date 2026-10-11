"""Step 2: execute every sampled migration and write its labels and its state (no model calls).

Per repo (one worker each), the schema-only database advances migration by migration (apply_progression). At each
sampled migration:
  1. empty run   - the migration on the schema with no rows (any error -> excluded: environment, not data);
  2. seed        - N_ROWS synthetic rows in every table, fixed RNG per item;
  3. state       - built from the seeded database (statebuild), before anything runs;
  4. auto run    - statements one by one in autocommit, continuing after errors -> lost / fails / half_applied;
  5. tx run      - the same in one transaction (secondary labels: what a transactional runner would do).
Output: data/items/<repo>.jsonl (one line per sampled migration, excluded ones too, with the reason).
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor

import pgexec as X
import statebuild as SB
from frame import R, ROOT, SEED, enumerate_repo
from sqlsplit import split_sql


def label_one(repo, rec, stmts, s_db):
    tag = repo[:10]
    e_db, seed_db, run_db, tx_db = f"e_{tag}", f"seed_{tag}", f"run_{tag}", f"tx_{tag}"
    out = dict(rec)
    X.clone_db(s_db, e_db)
    empty = X.run_statements(e_db, stmts)
    X.drop_db(e_db)
    out["empty_errors"] = [r["error"] for r in empty if r["ok"] is False]
    X.clone_db(s_db, seed_db)
    out["seeded_rows"] = X.seed(seed_db, random.Random(f"{SEED}:{repo}:{rec['mig']}"))
    st = SB.build_state(seed_db, stmts)
    out["state"] = st["prompt"]
    out["state_meta"] = {k: st[k] for k in ("shown", "named", "est_tokens", "level")}
    out["statements"] = stmts
    pre = X.snapshot(seed_db)
    X.clone_db(seed_db, run_db)
    res = X.run_statements(run_db, stmts)
    post = X.snapshot(run_db)
    L = X.loss_label(pre, post)
    fails = any(r["ok"] is False for r in res)
    changed = pre["schema"] != post["schema"] or X.data_fingerprint(pre) != X.data_fingerprint(post)
    out["label"] = {"lost": L["lost"], "fails": fails, "half_applied": fails and changed,
                    "first_fail": next((i + 1 for i, r in enumerate(res) if r["ok"] is False), None)}
    out["run"] = {"errors": [(i + 1, r["error"]) for i, r in enumerate(res) if r["ok"] is False],
                  "lost_detail": L["lost_detail"], "untracked_tables": L["untracked_tables"], "changed": changed}
    X.drop_db(run_db)
    X.clone_db(seed_db, tx_db)
    rtx = X.run_statements(tx_db, stmts, transaction=True)
    post_tx = X.snapshot(tx_db)
    Ltx = X.loss_label(pre, post_tx)
    out["label_tx"] = {"lost": Ltx["lost"], "fails": any(r["ok"] is False for r in rtx)}
    X.drop_db(tx_db)
    X.drop_db(seed_db)
    # exclusions (PREREG §4)
    ex = []
    if out["empty_errors"]:
        ex.append("fails_on_empty_schema")
    named = set(st["named"])
    if any(out["seeded_rows"].get(t, 0) == 0 for t in named if t in out["seeded_rows"]):
        ex.append("named_table_not_seeded")
    if any(t in named for t in L["untracked_tables"]):
        ex.append("untracked_rows")
    if st["est_tokens"] > SB.HARD_TOKENS:
        ex.append("state_too_long")
    out["excluded"] = ex
    return out


def process(repo):
    t0 = time.time()
    sample = [json.loads(l) for l in open(os.path.join(ROOT, "data", "sample.jsonl"))]
    want = {r["idx"]: r for r in sample if r["repo"] == repo}
    migs = enumerate_repo(repo)
    s_db = f"s_{repo[:10]}"
    X.create_db(s_db)
    path = os.path.join(ROOT, "data", "items", f"{repo}.jsonl")
    prog = {"tx": 0, "auto": 0, "auto-err": 0}
    with open(path, "w") as f:
        for idx, (mid, rel) in enumerate(migs):
            text = open(os.path.join(R, repo, rel), encoding="utf-8", errors="replace").read()
            stmts = split_sql(text)
            if idx in want:
                try:
                    out = label_one(repo, want[idx], stmts, s_db)
                except Exception as e:
                    out = dict(want[idx], excluded=["harness_error"], harness_error=f"{type(e).__name__}: {e}"[:500],
                               tb=traceback.format_exc()[-1500:])
                    for d in ("e_", "seed_", "run_", "tx_"):
                        try:
                            X.drop_db(d + repo[:10])
                        except Exception:
                            pass
                f.write(json.dumps(out, default=str) + "\n")
                f.flush()
            prog[X.apply_progression(s_db, stmts)] += 1
    X.drop_db(s_db)
    return repo, len(want), prog, round(time.time() - t0)


def main():
    os.makedirs(os.path.join(ROOT, "data", "items"), exist_ok=True)
    repos = sys.argv[1:] or sorted({json.loads(l)["repo"] for l in open(os.path.join(ROOT, "data", "sample.jsonl"))})
    with ProcessPoolExecutor(min(6, len(repos))) as ex:
        for repo, n, prog, secs in ex.map(process, repos):
            print(f"{repo:12s} items={n:3d} progression={prog} {secs}s", flush=True)


if __name__ == "__main__":
    main()
