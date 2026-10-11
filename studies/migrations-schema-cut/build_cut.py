"""Corte de schema, passo 1 (sem modelo): as mesmas migrações do v4 (D2 = as 582 do estudo; T2 = as 184 do v3),
reconstruídas pelo caminho do produto, guardando o catálogo ESTENDIDO (views, triggers, funções, sequências, domínios,
relações) do schema antes de cada migração. As estatísticas da réplica semeada vêm dos itens do v4 (mesma semente,
mesmo id), os rótulos ficam onde estão (labels_v3.jsonl para o T2).

    python build_cut.py SAMPLE V4_ITEMS_DIR OUT_DIR [repo ...]
"""
from __future__ import annotations

import glob, json, os, sys, time, traceback
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "ekbasis"))
sys.path.append(os.path.join(SP, "pr_study"))
from frame import R, enumerate_repo   # noqa: E402  frozen study code (read only)
from ekbasis import migrations as M   # noqa: E402  the branch under test

PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"
ADMIN = "postgresql://postgres@127.0.0.1:55497/postgres"
SAMPLE, V4, OUT = sys.argv[1:4]


def v4_items(repo):
    p = os.path.join(V4, f"{repo}.jsonl")
    return {json.loads(l)["id"]: json.loads(l) for l in open(p)} if os.path.exists(p) else {}


def product_raw(path, text, scratch, base_dirty, stats):
    """_check_file up to build_state (as build_v4.product_raw), with the branch's CATALOG."""
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


def process(repo):
    t0 = time.time()
    want = {r["idx"]: r for r in map(json.loads, open(SAMPLE)) if r["repo"] == repo}
    old = v4_items(repo)
    path = os.path.join(OUT, f"{repo}.jsonl")
    base_dirty = False
    with open(path, "w") as f, M.Scratch(ADMIN, PSQL) as scratch:
        for idx, (mid, rel) in enumerate(enumerate_repo(repo)):
            text = open(os.path.join(R, repo, rel), encoding="utf-8", errors="replace").read()
            if idx in want:
                iid = f"{repo}/{mid}"
                try:
                    v4 = old.get(iid, {}).get("raw") or {}
                    out = {"id": iid, "repo": repo, "path": rel,
                           "raw": product_raw(rel, text, scratch, base_dirty, v4.get("stats"))}
                    out["v4_same_inputs"] = (v4.get("decided") == out["raw"]["decided"] and
                                             (v4.get("catalog") or {}).get("tables") == (out["raw"].get("catalog") or {}).get("tables")
                                             and (v4.get("catalog") or {}).get("enums") == (out["raw"].get("catalog") or {}).get("enums"))
                except Exception as e:
                    out = {"id": iid, "repo": repo, "harness_error": f"{type(e).__name__}: {e}"[:500],
                           "tb": traceback.format_exc()[-1500:]}
                f.write(json.dumps(out, default=str) + "\n")
                f.flush()
            if scratch.db.apply(text, transaction=True):
                if scratch.db.apply(text, transaction=False):
                    base_dirty = True
    return repo, len(want), round(time.time() - t0)


def main():
    os.makedirs(OUT, exist_ok=True)
    repos = sys.argv[4:] or sorted({json.loads(l)["repo"] for l in open(SAMPLE)} - {"kratos"})
    with ProcessPoolExecutor(min(6, len(repos))) as ex:
        for repo, n, secs in ex.map(process, repos):
            print(f"{repo:12s} items={n:3d} {secs}s", flush=True)


if __name__ == "__main__":
    main()
