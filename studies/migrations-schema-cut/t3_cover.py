"""T3 (sem modelo): em cada repositório novo, a pasta PostgreSQL com mais migrações encontrada pelos DEFAULT_GLOBS do
produto; cada migração, antes de aplicada, tem a decisão em código e os estados OLD (_named_state, idêntico ao
build_state do 0.1.17) e NEW (corte) no regime N. Depois é aplicada como o produto faz (transação; em erro, autocommit).
    python3 t3_cover.py t3/repos OUT.jsonl"""
import collections, json, os, sys
sys.path.insert(0, "ekbasis")
from ekbasis import migrations as M

ROOT, OUT = sys.argv[1:3]
ADMIN = "postgresql://postgres@127.0.0.1:55497/postgres"
PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"
REPOS = ["AFFiNE", "ghostfolio", "typebot.io", "webstudio", "harbor", "concourse", "chirpstack", "fider"]

with open(OUT, "w") as out:
    for repo in REPOS:
        base = os.path.join(ROOT, repo)
        src = M.Source(base, None)
        files = [p for p in src.list(".") if M.is_migration(p)]
        files = [p[2:] if p.startswith("./") else p for p in files]
        sets = collections.defaultdict(list)
        for p in files:
            if not any(w in p.lower() for w in ("mysql", "sqlite", "mssql", "cockroach")):
                sets[(M.set_dir(p), M.tool_of(p))].append(p)
        if not sets:
            print(repo, "no PostgreSQL migration folder", flush=True)
            out.write(json.dumps({"repo": repo, "none": True}) + "\n")
            continue
        (folder, tool), fs = max(sets.items(), key=lambda kv: len(kv[1]))
        fs.sort()
        print(repo, folder, tool, len(fs), "files", flush=True)
        dirty = False
        with M.Scratch(ADMIN, PSQL) as scratch:
            for p in fs:
                text = src.read(p)
                stmts = M.split_sql(text)
                notes = []
                tx = M._transaction_for(tool, stmts, False, notes, text)
                rec = {"repo": repo, "path": p, "tool": tool, "statements": len(stmts), "chars_sql": len(text),
                       "dirty_base": dirty}
                if stmts:
                    probe = scratch.clone()
                    try:
                        err = probe.apply(text, transaction=tx)
                        code = probe.last_sqlstate
                    finally:
                        scratch.drop(probe)
                    if err and M.needs_privilege(code, err):
                        rec["decided"] = "cannot_foresee_privilege"
                    elif err and dirty:
                        rec["decided"] = "cannot_foresee_base"
                    elif err and tx:
                        rec["decided"] = "schema"
                    else:
                        cat = scratch.db.json(M.CATALOG) or {}
                        facts = [f"Run on this schema with no rows, the migration fails: {err}."] if err else []
                        old, _ = M._named_state(cat, stmts, None, tool, tx, facts)
                        nn = []
                        new, _ = M.build_state(cat, stmts, None, tool, tx, facts, notes=nn)
                        rec.update(decided=None, tables=len(cat.get("tables") or []), old=len(old), new=len(new),
                                   fallback=nn[0] if nn else None)
                else:
                    rec["decided"] = "ok_empty"
                out.write(json.dumps(rec) + "\n")
                out.flush()
                if scratch.db.apply(text, transaction=True):
                    if scratch.db.apply(text, transaction=False):
                        dirty = True
        print(repo, "done; base dirty" if dirty else "done", flush=True)
