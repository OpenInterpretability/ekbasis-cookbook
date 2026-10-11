"""Eval v2, step 1 (no model calls): re-execute the study's 599 sampled migrations with the frozen study pipeline and,
from the same seeded database, build the two new states:

  A2 (product): ekbasis.migrations.build_state at commit PRODUCT_COMMIT - the catalog read with the product's query,
     planner statistics after ANALYZE (rows, NULL fraction, distinct counts; no rows, no values, no literal counts),
     the transactional rule of the file's tool (autocommit for files the product checks in autocommit).
  A1 (ablation): the study's v1 state (statebuild.build_state: sample rows, per-column facts, literal counts) with the
     product's rules text in place of the autocommit rules.

Labels: the frozen labeler, both regimes (autocommit run and one-transaction run), as in the study.
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
from frame import R, SEED, enumerate_repo   # noqa: E402
from sqlsplit import split_sql        # noqa: E402
from ekbasis import migrations as M   # noqa: E402  the product

PSQL = os.environ.get("EKBASIS_PSQL", "/opt/homebrew/opt/postgresql@16/bin/psql")
URL = "postgresql://postgres@127.0.0.1:55491/{db}"


def product_regime(stmts):
    return not any(M.NO_TX.search(s) for s in stmts)


def a1_state(v1_prompt: str, tool: str, tx: bool) -> str:
    rules = M.RULES_TX.format(tool=M.TOOL_NAMES.get(tool, M.TOOL_NAMES["generic"])) if tx else M.RULES_AUTO
    assert v1_prompt.startswith(SB.RULES)
    return rules + v1_prompt[len(SB.RULES):]


def label_one(repo, rec, stmts, text, s_db):
    tag = repo[:10]
    e_db, seed_db, run_db, tx_db = f"e2_{tag}", f"seed2_{tag}", f"run2_{tag}", f"tx2_{tag}"
    out = {k: rec[k] for k in ("repo", "mig", "path", "stratum", "idx")}
    X.clone_db(s_db, e_db)
    empty = X.run_statements(e_db, stmts)
    X.drop_db(e_db)
    out["empty_errors"] = [r["error"] for r in empty if r["ok"] is False]
    X.clone_db(s_db, seed_db)
    out["seeded_rows"] = X.seed(seed_db, random.Random(f"{SEED}:{repo}:{rec['mig']}"))
    tool = M.tool_of(rec["path"])
    pstmts = M.split_sql(text)               # what the product reads (same splitter as the study's)
    tx = product_regime(pstmts)
    st = SB.build_state(seed_db, stmts)          # v1 builder (read-only)
    out["state_meta"] = {k: st[k] for k in ("shown", "named", "est_tokens", "level")}
    out["state_a1"] = a1_state(st["prompt"], tool, tx)
    pg = M.Pg(URL.format(db=seed_db), PSQL)
    pg.run(["-c", "ANALYZE"])
    catalog = pg.json(M.CATALOG) or {}
    stats = pg.json(M.STATS)
    out["state_a2"], out["shown_a2"] = M.build_state(catalog, pstmts, stats, tool, tx)
    out["tool"], out["transaction"] = tool, tx
    out["n_statements"] = len(stmts)
    pre = X.snapshot(seed_db)
    X.clone_db(seed_db, run_db)
    res = X.run_statements(run_db, stmts)
    post = X.snapshot(run_db)
    L = X.loss_label(pre, post)
    fails = any(r["ok"] is False for r in res)
    changed = pre["schema"] != post["schema"] or X.data_fingerprint(pre) != X.data_fingerprint(post)
    out["label"] = {"lost": L["lost"], "fails": fails, "half_applied": fails and changed}
    out["untracked"] = L["untracked_tables"]
    X.drop_db(run_db)
    X.clone_db(seed_db, tx_db)
    rtx = X.run_statements(tx_db, stmts, transaction=True)
    post_tx = X.snapshot(tx_db)
    out["label_tx"] = {"lost": X.loss_label(pre, post_tx)["lost"], "fails": any(r["ok"] is False for r in rtx)}
    X.drop_db(tx_db)
    X.drop_db(seed_db)
    # the label of the regime the product states: one transaction, or autocommit where the product uses it
    out["label_product"] = dict(out["label_tx"]) if tx else {"lost": out["label"]["lost"], "fails": out["label"]["fails"]}
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
    sample = [json.loads(l) for l in open(os.path.join(STUDY, "data", "sample.jsonl"))]
    want = {r["idx"]: r for r in sample if r["repo"] == repo}
    migs = enumerate_repo(repo)
    s_db = f"s2_{repo[:10]}"
    X.create_db(s_db)
    path = os.path.join(HERE, "data", "items", f"{repo}.jsonl")
    with open(path, "w") as f:
        for idx, (mid, rel) in enumerate(migs):
            text = open(os.path.join(R, repo, rel), encoding="utf-8", errors="replace").read()
            stmts = split_sql(text)
            if idx in want:
                try:
                    out = label_one(repo, want[idx], stmts, text, s_db)
                except Exception as e:
                    out = dict(repo=repo, mig=mid, excluded=["harness_error"], harness_error=f"{type(e).__name__}: {e}"[:500],
                               tb=traceback.format_exc()[-1500:])
                    for d in ("e2_", "seed2_", "run2_", "tx2_"):
                        try:
                            X.drop_db(d + repo[:10])
                        except Exception:
                            pass
                f.write(json.dumps(out, default=str) + "\n")
                f.flush()
            X.apply_progression(s_db, stmts)
    X.drop_db(s_db)
    return repo, len(want), round(time.time() - t0)


def main():
    os.makedirs(os.path.join(HERE, "data", "items"), exist_ok=True)
    repos = sys.argv[1:] or sorted({json.loads(l)["repo"] for l in open(os.path.join(STUDY, "data", "sample.jsonl"))})
    with ProcessPoolExecutor(min(6, len(repos))) as ex:
        for repo, n, secs in ex.map(process, repos):
            print(f"{repo:12s} items={n:3d} {secs}s", flush=True)


if __name__ == "__main__":
    main()
