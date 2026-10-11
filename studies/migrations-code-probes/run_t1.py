"""P2 (from v4 run_t1.py), T1: each frozen incident's PR (base = first parent of the commit that added the migration, head = that commit),
checked by the INSTALLED ekbasis through migrations.check (what `migrate-check --base --head` runs), in regime R
(seeded replica, the study's seeder) and N (no replica). Hosted API, study key, concurrency 1, cache off.

    venv_old/bin/python run_t1.py old INCIDENTS.jsonl      -> results/t1_old/<id>.json
    venv_new/bin/python run_t1.py new INCIDENTS.jsonl      -> results/t1_new/<id>.json  (reuses OLD's answer when the
                                                              state is byte-identical, PREREG_v4 section 4)
Also run_t1.py prep INCIDENTS.jsonl (no model): base/head, prefetch, replica sanity, synthetic label, regex rules.
"""
from __future__ import annotations

import glob, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.dirname(HERE)
sys.path.append(os.path.join(SP, "pr_study"))
import pgexec as X                                          # noqa: E402
import rules as RU                                          # noqa: E402
from ekbasis import migrations as M                         # noqa: E402
from ekbasis.client import Ekbasis                          # noqa: E402

PORT = 55493
X.DSN = f"host=127.0.0.1 port={PORT} user=postgres"
ADMIN = f"postgresql://postgres@127.0.0.1:{PORT}/postgres"
PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"
REPOS = os.path.join(HERE, "repos")
URL = "https://openinterp.org/api/v1"


def git(repo, *a):
    import subprocess
    r = subprocess.run(["git", "-C", os.path.join(REPOS, repo), *a], capture_output=True, text=True, errors="replace")
    if r.returncode:
        raise RuntimeError(f"git {a}: {r.stderr[:300]}")
    return r.stdout


def glob_for(path):
    folder, tool = M.set_dir(path), M.tool_of(path)
    return {"prisma": f"{folder}/*/migration.sql", "diesel": f"{folder}/*/up.sql",
            "golang-migrate": f"{folder}/*.up.sql"}.get(tool, f"{folder}/*.sql")


def replica(c, base, db):
    folder, tool, g = M.set_dir(c["path"]), M.tool_of(c["path"]), (glob_for(c["path"]),)
    src = M.Source(os.path.join(REPOS, c["repo"]), base)
    prior = [p for p in src.list(folder) if M.is_migration(p, g) and M.tool_of(p) == tool and M.set_dir(p) == folder]
    X.create_db(db)
    pg = M.Pg(f"postgresql://postgres@127.0.0.1:{PORT}/{db}", PSQL)
    errs = sum(1 for p in prior if pg.apply(src.read(p), transaction=True) and pg.apply(src.read(p), transaction=False))
    seeded = X.seed(db, random.Random(f"p2:{c['id']}"))
    with X.connect(db) as con:
        con.execute("ANALYZE")
    return {"prior": len(prior), "prior_errors": errs, "rows": sum(seeded.values())}


class Reuse:
    """NEW's client: OLD's probabilities when the state is byte-identical to OLD's, else the hosted model."""

    def __init__(self, old_by_state):
        self.real = Ekbasis(url=URL, api_key=open(os.path.expanduser("~/.config/ekbasis/study_api_key")).read().strip())
        self.url = self.real.url
        self.old = old_by_state
        self.calls = 0
        self.reused = 0

    def ask(self, state, qs):
        if state in self.old and set(self.old[state]) == set(qs):
            self.reused += 1
            from ekbasis.client import Answer
            return {k: Answer(value=p >= 0.5, confidence=max(p, 1 - p), probabilities={"yes": p, "no": 1 - p}, p_yes=p)
                    for k, p in self.old[state].items()}
        self.calls += 1
        return self.real.ask(state, qs)


def main():
    mode, inc = sys.argv[1], sys.argv[2]
    os.environ["EKBASIS_VERDICT_CACHE"] = "off"
    os.environ["EKBASIS_PSQL"] = PSQL
    out_dir = os.path.join(HERE, "results", f"t1_{mode}")
    os.makedirs(out_dir, exist_ok=True)
    for c in map(json.loads, open(inc)):
        if c.get("in_scope") is False:
            continue
        out = os.path.join(out_dir, c["id"] + ".json")
        if os.path.exists(out):
            continue
        rec = {"id": c["id"]}
        try:
            head = git(c["repo"], "rev-parse", c["add"]).strip()
            base = git(c["repo"], "rev-parse", head + "^1").strip()
            rec.update(base=base, head=head)
            git(c["repo"], "sparse-checkout", "set", "--no-cone", f"/{M.set_dir(c['path'])}/")
            for ref in (base, head):
                git(c["repo"], "checkout", "-q", "-f", "--detach", ref)
            os.environ["EKBASIS_SURFACE"] = "pr-study-p2-test"
            db = "t1_" + c["id"].replace("-", "_")[:40]
            rec["replica"] = replica(c, base, db)
            if mode == "prep":
                text = git(c["repo"], "show", f"{head}:{c['path']}")
                stmts = M.split_sql(M.goose_up(text))
                rec["rules"] = {"R3": RU.r3(stmts), "F1": RU.f1(stmts)}
                tx = M._transaction_for(M.tool_of(c["path"]), stmts, False, [], text)
                X.clone_db(db, db + "_r")
                pre = X.snapshot(db + "_r")
                res = X.run_statements(db + "_r", stmts, transaction=tx)
                rec["synthetic"] = {"fails": any(r["ok"] is False for r in res),
                                    "lost": X.loss_label(pre, X.snapshot(db + "_r"))["lost"],
                                    "errors": [r["error"] for r in res if r["ok"] is False][:2]}
                X.drop_db(db + "_r")
            else:
                old = {}
                if mode == "new":
                    po = os.path.join(HERE, "results", "t1_old", c["id"] + ".json")
                    d = json.load(open(po))
                    for arm in ("R", "N"):
                        for f in d.get(arm, {}).get("files", []):
                            if f.get("state") and f.get("p_lost") is not None and not f.get("schema_error"):
                                old[f["state"]] = {k: v for k, v in (("lost", f["p_lost"]), ("fails", f["p_fail"]),
                                                                     ("half", f["p_half"])) if v is not None}
                for arm, su in (("R", f"postgresql://postgres@127.0.0.1:{PORT}/{db}"), ("N", None)):
                    cl = Reuse(old) if mode == "new" else Ekbasis(url=URL, api_key=open(os.path.expanduser(
                        "~/.config/ekbasis/study_api_key")).read().strip())
                    v = M.check(os.path.join(REPOS, c["repo"]), base=base, head=head, globs=(glob_for(c["path"]),),
                                pg_url=ADMIN, stats_url=su, client=cl, psql=PSQL)
                    rec[arm] = v.as_json(state=True)
                    if mode == "new":
                        rec[arm]["calls"], rec[arm]["reused"] = cl.calls, cl.reused
            X.drop_db(db)
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"[:500]
        json.dump(rec, open(out, "w"), indent=1)
        f = lambda a: next((x for x in rec.get(a, {}).get("files", []) if x["path"] == c["path"]), {})
        print(c["id"], rec.get("error") or (f("R").get("kind"), f("N").get("kind")), flush=True)


if __name__ == "__main__":
    main()
