"""v4, T2 step 1 (no model calls): the 184 migrations of the v3 sample, rebuilt by the v3 pipeline (same sample, same
seed string), now keeping the RAW inputs of the product side so that OLD and NEW states come from the same inputs:
the catalog of the role-built schema before the migration, the statements, the planner statistics of the seeded
database (the replica), the transaction mode, the schema probe's error and the decisions in code that are common to
both versions (privilege, incomplete base, failure on the schema).

Product-side code is the NEW branch's (identical to OLD outside constraint_facts). Labels: the frozen executor, for the
divergence check only (truth stays labels_v3.jsonl).

    venv_new/bin/python build_v4.py            -> data/items_v4/<repo>.jsonl   (T2)
    V4_SAMPLE=../pr_study/data/sample.jsonl V4_SEED=20261010 V4_OUT=data/items_d2 venv_new/bin/python build_v4.py
                                               -> the study's 582 (D2, development; kratos left out)
"""
from __future__ import annotations

import json, os, random, sys, time, traceback
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.dirname(HERE)
sys.path.append(os.path.join(SP, "pr_study"))
import pgexec as X                    # noqa: E402  frozen study code
import statebuild as SB               # noqa: E402
from frame import R, enumerate_repo   # noqa: E402
from sqlsplit import split_sql        # noqa: E402
from ekbasis import migrations as M   # noqa: E402

PORT = 55493
X.DSN = f"host=127.0.0.1 port={PORT} user=postgres"
SEED = os.environ.get("V4_SEED", "20261011:v3")         # the v3 seed string, unchanged
PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"
ADMIN = f"postgresql://postgres@127.0.0.1:{PORT}/postgres"
SAMPLE = os.environ.get("V4_SAMPLE", os.path.join(SP, "pr_eval3", "data", "sample_v3.jsonl"))
OUT = os.environ.get("V4_OUT", os.path.join(HERE, "data", "items_v4"))


def product_raw(path, text, scratch, base_dirty, stats):
    """Mirrors _check_file at 8071e38 up to build_state, and returns the inputs instead of the state."""
    stmts = M.split_sql(text)
    tool = M.tool_of(path)
    notes = []
    tx = M._transaction_for(tool, stmts, False, notes, text)
    out = {"tool": tool, "transaction": tx, "statements": stmts, "decided": None, "schema_error": None, "notes": notes}
    if not stmts:
        out["decided"] = "ok_empty"
        return out
    probe = scratch.clone()
    try:
        err = probe.apply(text, transaction=tx)
        code = probe.last_sqlstate
    finally:
        scratch.drop(probe)
    out["schema_error"] = err
    if err and M.needs_privilege(code, err):
        out["decided"] = "cannot_foresee_privilege"
    elif err and base_dirty:
        out["decided"] = "cannot_foresee_base"
    elif err and tx:
        out["decided"] = "schema"
    else:
        out["catalog"] = scratch.db.json(M.CATALOG) or {}
        out["stats"] = stats
    return out


def label_side(repo, rec, stmts, s_db):
    tag = repo[:10]
    e_db, seed_db, run_db, tx_db = f"e4_{tag}", f"seed4_{tag}", f"run4_{tag}", f"tx4_{tag}"
    out = {}
    X.clone_db(s_db, e_db)
    out["empty_errors"] = [r["error"] for r in X.run_statements(e_db, stmts) if r["ok"] is False]
    X.drop_db(e_db)
    X.clone_db(s_db, seed_db)
    out["seeded_rows"] = X.seed(seed_db, random.Random(f"{SEED}:{repo}:{rec['mig']}"))
    pg = M.Pg(f"postgresql://postgres@127.0.0.1:{PORT}/{seed_db}", PSQL)
    pg.run(["-c", "ANALYZE"])
    stats = pg.json(M.STATS)
    pre = X.snapshot(seed_db)
    X.clone_db(seed_db, tx_db)
    rtx = X.run_statements(tx_db, stmts, transaction=True)
    out["label_tx"] = {"lost": X.loss_label(pre, X.snapshot(tx_db))["lost"], "fails": any(r["ok"] is False for r in rtx)}
    X.drop_db(tx_db)
    X.clone_db(seed_db, run_db)
    res = X.run_statements(run_db, stmts)
    out["label_auto"] = {"lost": X.loss_label(pre, X.snapshot(run_db))["lost"], "fails": any(r["ok"] is False for r in res)}
    X.drop_db(run_db)
    X.drop_db(seed_db)
    return out, stats


def process(repo):
    t0 = time.time()
    want = {r["idx"]: r for r in map(json.loads, open(SAMPLE)) if r["repo"] == repo}
    s_db = f"s4_{repo[:10]}"
    X.create_db(s_db)
    path = os.path.join(OUT, f"{repo}.jsonl")
    base_dirty = False
    with open(path, "w") as f, M.Scratch(ADMIN, PSQL) as scratch:
        for idx, (mid, rel) in enumerate(enumerate_repo(repo)):
            text = open(os.path.join(R, repo, rel), encoding="utf-8", errors="replace").read()
            stmts = split_sql(text)
            if idx in want:
                rec = want[idx]
                try:
                    lab, stats = label_side(repo, rec, stmts, s_db)
                    out = {"id": f"{repo}/{mid}", "repo": repo, "path": rel, **lab,
                           "raw": product_raw(rel, text, scratch, base_dirty, stats)}
                except Exception as e:
                    out = {"id": f"{repo}/{mid}", "repo": repo, "harness_error": f"{type(e).__name__}: {e}"[:500],
                           "tb": traceback.format_exc()[-1500:]}
                    for d in ("e4_", "seed4_", "run4_", "tx4_"):
                        try:
                            X.drop_db(d + repo[:10])
                        except Exception:
                            pass
                f.write(json.dumps(out, default=str) + "\n")
                f.flush()
            X.apply_progression(s_db, stmts)
            if scratch.db.apply(text, transaction=True):
                if scratch.db.apply(text, transaction=False):
                    base_dirty = True
    X.drop_db(s_db)
    return repo, len(want), round(time.time() - t0)


def main():
    os.makedirs(OUT, exist_ok=True)
    repos = sys.argv[1:] or sorted({json.loads(l)["repo"] for l in open(SAMPLE)} - {"kratos"})
    with ProcessPoolExecutor(min(6, len(repos))) as ex:
        for repo, n, secs in ex.map(process, repos):
            print(f"{repo:12s} items={n:3d} {secs}s", flush=True)


if __name__ == "__main__":
    main()
