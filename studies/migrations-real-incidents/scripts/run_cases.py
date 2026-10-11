"""Step 2: for each candidate, reconstruct the PR (base = first parent of the commit that added the bad migration, head =
that commit) and run `ekbasis migrate-check` (client 0.1.12) as the Action does, against the hosted API, concurrency 1.

Per candidate:
  1. sparse checkout of the migration folder at base and head (fetches the blobs of a blob-less clone in one batch);
  2. replica for statistics: the base's migrations applied in the guard's order to a database on the local PostgreSQL 16,
     seeded with the study's generic seeder (20 rows/table, NULL p=0.25, FKs to seeded parents), then ANALYZE;
  3. synthetic label: the head migration run once on a copy of the seeded replica, in one transaction (the product's
     regime; autocommit when the file cannot run in one), with the study's loss labeler;
  4. `ekbasis migrate-check --base B --head H --json` with --stats-url (primary) and without (the Action's default when no
     replica is configured);
  5. the study's regex baselines on the head file (R3 for loss, F1 for failure).

    python run_cases.py [--only ID ...] [--no-model]
"""
from __future__ import annotations

import argparse, glob, json, os, random, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, glob.glob(os.path.join(HERE, "venv/lib/python*/site-packages"))[0])
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pr_study"))  # the frozen study scripts: ../migrations/frozen in the cookbook
import pgexec as X                                          # noqa: E402  (study executor, frozen)
import rules as RU                                          # noqa: E402  (study regex baselines)
from ekbasis import migrations as M                         # noqa: E402
from candidates import C                                    # noqa: E402

PORT = 55493
X.DSN = f"host=127.0.0.1 port={PORT} user=postgres"
ADMIN = f"postgresql://postgres@127.0.0.1:{PORT}/postgres"
PSQL = os.environ.get("EKBASIS_PSQL", "psql")              # sanitized: was a local absolute path
EKB = os.path.join(HERE, "venv/bin/ekbasis")
REPOS = os.path.join(HERE, "repos")
OUT = os.path.join(HERE, "results")


def git(repo, *a, check=True):
    r = subprocess.run(["git", "-C", os.path.join(REPOS, repo), *a], capture_output=True, text=True, errors="replace")
    if check and r.returncode:
        raise RuntimeError(f"git {a}: {r.stderr[:300]}")
    return r.stdout


def resolve(c):
    if not c.get("add"):
        c["add"] = git(c["repo"], "log", "--first-parent", "--diff-filter=A", "--format=%H", "--", c["path"]).split()[-1]
    head = git(c["repo"], "rev-parse", c["add"]).strip()
    base = git(c["repo"], "rev-parse", head + "^1").strip()
    return base, head


def prefetch(c, base, head):
    folder = M.set_dir(c["path"])
    git(c["repo"], "sparse-checkout", "set", "--no-cone", f"/{folder}/")
    for ref in (base, head):
        git(c["repo"], "checkout", "-q", "-f", "--detach", ref)


def glob_for(c):
    folder = M.set_dir(c["path"])
    tool = M.tool_of(c["path"])
    return {"prisma": f"{folder}/*/migration.sql", "diesel": f"{folder}/*/up.sql",
            "golang-migrate": f"{folder}/*.up.sql"}.get(tool, f"{folder}/*.sql")


def build_replica(c, base, db):
    """The base's migrations of the folder, in the guard's order and with its fallback (one transaction, then
    autocommit), as the superuser; then the study's seeder and ANALYZE."""
    folder, tool, g = M.set_dir(c["path"]), M.tool_of(c["path"]), (glob_for(c),)
    src = M.Source(os.path.join(REPOS, c["repo"]), base)
    prior = [p for p in src.list(folder) if M.is_migration(p, g) and M.tool_of(p) == tool and M.set_dir(p) == folder]
    X.create_db(db)
    pg = M.Pg(f"postgresql://postgres@127.0.0.1:{PORT}/{db}", PSQL)
    errs = 0
    for p in prior:
        sql = src.read(p)
        if pg.apply(sql, transaction=True) and pg.apply(sql, transaction=False):
            errs += 1
    seeded = X.seed(db, random.Random(f"real_cases:{c['id']}"))
    with X.connect(db) as con:
        con.execute("ANALYZE")
    return {"prior": len(prior), "prior_errors": errs, "tables_seeded": sum(1 for v in seeded.values() if v),
            "rows": sum(seeded.values())}


def synthetic_label(c, head, seed_db):
    text = git(c["repo"], "show", f"{head}:{c['path']}")
    stmts = M.split_sql(text)
    tx = not any(M.NO_TX.search(s) for s in stmts)
    run_db = seed_db + "_run"
    X.clone_db(seed_db, run_db)
    pre = X.snapshot(run_db)
    res = X.run_statements(run_db, stmts, transaction=tx)
    post = X.snapshot(run_db)
    L = X.loss_label(pre, post)
    X.drop_db(run_db)
    return stmts, {"regime": "transaction" if tx else "autocommit", "fails": any(r["ok"] is False for r in res),
                   "lost": L["lost"], "errors": [(i + 1, r["error"]) for i, r in enumerate(res) if r["ok"] is False][:3],
                   "lost_detail": str(L.get("lost_detail"))[:300]}


def guard(c, base, head, stats_url):
    env = dict(os.environ, EKBASIS_URL="https://openinterp.org/api/v1", EKBASIS_PSQL=PSQL,
               EKBASIS_API_KEY=os.environ["EKBASIS_API_KEY"])  # sanitized: the run read a local key file
    cmd = [EKB, "migrate-check", "--repo", os.path.join(REPOS, c["repo"]), "--base", base, "--head", head, "--json",
           "--show-state", "--pg-url", ADMIN, "--glob", glob_for(c)]
    if stats_url:
        cmd += ["--stats-url", stats_url]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=900)
    raw = r.stdout.strip().splitlines()
    try:
        res = json.loads(raw[-1]) if raw else {}
    except ValueError:
        res = {"unparsed": r.stdout[-500:]}
    return {"exit": r.returncode, "secs": round(time.time() - t0, 1), "result": res, "stderr": r.stderr[-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-model", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    for c in C:
        if a.only and c["id"] not in a.only:
            continue
        out = os.path.join(OUT, c["id"] + ".json")
        if os.path.exists(out) and not a.only:
            continue
        rec = {k: v for k, v in c.items()}
        try:
            base, head = resolve(c)
            rec.update(base=base, head=head, add=head)
            prefetch(c, base, head)
            db = "st_" + c["id"].replace("-", "_")[:40]
            rec["replica"] = build_replica(c, base, db)
            stmts, rec["synthetic"] = synthetic_label(c, head, db)
            rec["statements"] = len(stmts)
            rec["rules"] = {"R3": RU.r3(stmts), "F1": RU.f1(stmts), "R1": RU.r1(stmts)}
            if not a.no_model:
                rec["guard_stats"] = guard(c, base, head, f"postgresql://postgres@127.0.0.1:{PORT}/{db}")
                rec["guard_nostats"] = guard(c, base, head, None)
            X.drop_db(db)
        except Exception as e:                                  # recorded, never skipped silently
            rec["error"] = f"{type(e).__name__}: {e}"[:500]
        json.dump(rec, open(out, "w"), indent=1)
        g = (rec.get("guard_stats") or {}).get("result", {})
        f = next((x for x in g.get("files", []) if x.get("path") == c["path"]), None)
        print(c["id"], rec.get("error") or (f and (f["kind"], f.get("p_lost"), f.get("p_fail"))) or g, flush=True)


if __name__ == "__main__":
    main()
