"""Eval v3, step 1 (no model calls). For each migration of data/sample_v3.jsonl:

- PRODUCT side, with the product's own code at PRODUCT_COMMIT (ekbasis.migrations): the schema is built the way
  `migrate-check` builds it (each earlier migration of the repo applied by Scratch.db.apply as the throwaway
  non-superuser role: one transaction, then autocommit if that fails); the migration is probed on that schema alone;
  privilege errors, an incomplete base, and failures on the schema are decided in code as in _check_file; otherwise the
  state is build_state(catalog of the role-built schema, statements, planner statistics of the seeded database).
- LABEL side, with the study's frozen executor: the seeded database (20 synthetic rows per table), the run in
  autocommit and in one transaction, the frozen labeler. The planner statistics are read from that seeded database
  after ANALYZE (it plays the read-only replica).

Output: data/items/<repo>.jsonl. Needs the local PostgreSQL 16 on 127.0.0.1:55491.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.join(os.path.dirname(HERE), "pr_study")
PRODUCT = os.path.join(os.path.dirname(HERE), "migguard_ekbasis")
sys.path.insert(0, STUDY)
sys.path.insert(0, PRODUCT)

import pgexec as X                    # noqa: E402  frozen study code
import statebuild as SB               # noqa: E402
from frame import R, enumerate_repo   # noqa: E402
from sqlsplit import split_sql        # noqa: E402
from ekbasis import migrations as M   # noqa: E402  the product

SEED = "20261011:v3"
PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"
ADMIN = "postgresql://postgres@127.0.0.1:55491/postgres"


def product_side(path, text, scratch, base_dirty, stats):
    """What migrate-check decides before asking the model, and the state it would send (mirrors _check_file)."""
    stmts = M.split_sql(text)
    tool = M.tool_of(path)
    notes = []
    tx = M._transaction_for(tool, stmts, False, notes)
    out = {"tool": tool, "transaction": tx, "n_statements": len(stmts), "decided": None, "schema_error": None}
    if not stmts:
        out["decided"] = "ok_empty"
        return out
    probe = scratch.clone()
    try:
        err = probe.apply(text, transaction=tx)
        code = probe.last_sqlstate
    finally:
        scratch.drop(probe)
    if err and M.needs_privilege(code, err):
        out["decided"] = "cannot_foresee_privilege"
        out["schema_error"] = err
        return out
    if err and base_dirty:
        out["decided"] = "cannot_foresee_base"
        out["schema_error"] = err
        return out
    if err and tx:
        out["decided"] = "schema"
        out["schema_error"] = err
        return out
    facts = [f"Run on this schema with no rows, the migration fails: {err}."] if err else []
    out["schema_error"] = err
    out["state"], out["shown"] = M.build_state(scratch.db.json(M.CATALOG) or {}, stmts, stats, tool, tx, facts)
    if len(out["state"]) > M.MAX_CHARS:
        out["decided"] = "cannot_foresee_long"
    return out


def label_side(repo, rec, stmts, s_db):
    tag = repo[:10]
    e_db, seed_db, run_db, tx_db = f"e3_{tag}", f"seed3_{tag}", f"run3_{tag}", f"tx3_{tag}"
    out = {}
    X.clone_db(s_db, e_db)
    out["empty_errors"] = [r["error"] for r in X.run_statements(e_db, stmts) if r["ok"] is False]
    X.drop_db(e_db)
    X.clone_db(s_db, seed_db)
    out["seeded_rows"] = X.seed(seed_db, random.Random(f"{SEED}:{repo}:{rec['mig']}"))
    st = SB.build_state(seed_db, stmts)                       # only for the study's exclusion rules
    pg = M.Pg(f"postgresql://postgres@127.0.0.1:55491/{seed_db}", PSQL)
    pg.run(["-c", "ANALYZE"])
    stats = pg.json(M.STATS)
    pre = X.snapshot(seed_db)
    X.clone_db(seed_db, run_db)
    res = X.run_statements(run_db, stmts)
    post = X.snapshot(run_db)
    L = X.loss_label(pre, post)
    fails = any(r["ok"] is False for r in res)
    changed = pre["schema"] != post["schema"] or X.data_fingerprint(pre) != X.data_fingerprint(post)
    out["label"] = {"lost": L["lost"], "fails": fails, "half_applied": fails and changed}
    X.drop_db(run_db)
    X.clone_db(seed_db, tx_db)
    rtx = X.run_statements(tx_db, stmts, transaction=True)
    out["label_tx"] = {"lost": X.loss_label(pre, X.snapshot(tx_db))["lost"], "fails": any(r["ok"] is False for r in rtx)}
    X.drop_db(tx_db)
    X.drop_db(seed_db)
    ex = []
    if out["empty_errors"]:
        ex.append("fails_on_empty_schema")
    named = set(st["named"])
    if any(out["seeded_rows"].get(t, 0) == 0 for t in named if t in out["seeded_rows"]):
        ex.append("named_table_not_seeded")
    if any(t in named for t in L["untracked_tables"]):
        ex.append("untracked_rows")
    out["excluded"] = ex
    return out, stats


def process(repo):
    t0 = time.time()
    sample = [json.loads(l) for l in open(os.path.join(HERE, "data", "sample_v3.jsonl"))]
    want = {r["idx"]: r for r in sample if r["repo"] == repo}
    s_db = f"s3_{repo[:10]}"
    X.create_db(s_db)
    path = os.path.join(HERE, "data", "items", f"{repo}.jsonl")
    base_dirty = False
    with open(path, "w") as f, M.Scratch(ADMIN, PSQL) as scratch:
        for idx, (mid, rel) in enumerate(enumerate_repo(repo)):
            text = open(os.path.join(R, repo, rel), encoding="utf-8", errors="replace").read()
            stmts = split_sql(text)
            if idx in want:
                rec = want[idx]
                try:
                    lab, stats = label_side(repo, rec, stmts, s_db)
                    prod = product_side(rel, text, scratch, base_dirty, stats)
                    out = {"id": f"{repo}/{mid}", "repo": repo, "mig": mid, "path": rel, "stratum": rec["stratum"],
                           "file_sha256": rec["sha256"], "commit": rec["commit"], **lab, "product": prod}
                    out["label_product"] = (dict(lab["label_tx"]) if prod["transaction"]
                                            else {"lost": lab["label"]["lost"], "fails": lab["label"]["fails"]})
                except Exception as e:
                    out = {"id": f"{repo}/{mid}", "repo": repo, "excluded": ["harness_error"],
                           "harness_error": f"{type(e).__name__}: {e}"[:500], "tb": traceback.format_exc()[-1500:]}
                    for d in ("e3_", "seed3_", "run3_", "tx3_"):
                        try:
                            X.drop_db(d + repo[:10])
                        except Exception:
                            pass
                f.write(json.dumps(out, default=str) + "\n")
                f.flush()
            X.apply_progression(s_db, stmts)                               # the label side's schema (study)
            if scratch.db.apply(text, transaction=True):                   # the product's schema (role)
                if scratch.db.apply(text, transaction=False):
                    base_dirty = True
    X.drop_db(s_db)
    return repo, len(want), round(time.time() - t0)


def main():
    os.makedirs(os.path.join(HERE, "data", "items"), exist_ok=True)
    repos = sys.argv[1:] or sorted({json.loads(l)["repo"] for l in open(os.path.join(HERE, "data", "sample_v3.jsonl"))})
    with ProcessPoolExecutor(min(6, len(repos))) as ex:
        for repo, n, secs in ex.map(process, repos):
            print(f"{repo:12s} items={n:3d} {secs}s", flush=True)


if __name__ == "__main__":
    main()
