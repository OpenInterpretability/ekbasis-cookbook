"""Development (no model calls): the states the installed ekbasis builds for the 34 real_cases candidates, with the
seeded replica (R) and without (N). A stub client records the state and answers 0. Run with venv_old or venv_new.

    venv_new/bin/python dev_states.py OUT.jsonl [--only ID ...]
"""
from __future__ import annotations

import argparse, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RC = os.path.join(os.path.dirname(HERE), "real_cases")
sys.path.append(os.path.join(os.path.dirname(HERE), "pr_study"))
sys.path.append(RC)
import pgexec as X                                   # noqa: E402  study executor (seeder)
from ekbasis import migrations as M                  # noqa: E402  the installed product (old or new)
from ekbasis.client import Answer                    # noqa: E402
from candidates import C as C_RC                      # noqa: E402
for c in C_RC:
    c["_repos"], c["_res"] = os.path.join(RC, "repos"), os.path.join(RC, "results", c["id"] + ".json")
V4 = os.path.join(os.path.dirname(HERE), "v4")
C_V4 = [json.loads(l) for l in open(os.path.join(V4, "incidents_v4.jsonl"))]
for c in C_V4:
    c["_repos"], c["_res"] = os.path.join(V4, "repos"), os.path.join(V4, "results", "t1_old", c["id"] + ".json")
C = C_RC + C_V4

PORT = 55493
X.DSN = f"host=127.0.0.1 port={PORT} user=postgres"
ADMIN = f"postgresql://postgres@127.0.0.1:{PORT}/postgres"
PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"


class Stub:
    url = "stub"

    def __init__(self):
        self.states = []

    def ask(self, state, qs):
        self.states.append(state)
        return {k: Answer(value=False, confidence=1.0, probabilities={"yes": 0.0, "no": 1.0}, p_yes=0.0) for k in qs}


def glob_for(path):
    folder, tool = M.set_dir(path), M.tool_of(path)
    return {"prisma": f"{folder}/*/migration.sql", "diesel": f"{folder}/*/up.sql",
            "golang-migrate": f"{folder}/*.up.sql"}.get(tool, f"{folder}/*.sql")


def replica(c, base, db):
    folder, tool, g = M.set_dir(c["path"]), M.tool_of(c["path"]), (glob_for(c["path"]),)
    src = M.Source(os.path.join(c["_repos"], c["repo"]), base)
    prior = [p for p in src.list(folder) if M.is_migration(p, g) and M.tool_of(p) == tool and M.set_dir(p) == folder]
    X.create_db(db)
    pg = M.Pg(f"postgresql://postgres@127.0.0.1:{PORT}/{db}", PSQL)
    for p in prior:
        sql = src.read(p)
        if pg.apply(sql, transaction=True):
            pg.apply(sql, transaction=False)
    X.seed(db, random.Random(f"real_cases:{c['id']}"))
    with X.connect(db) as con:
        con.execute("ANALYZE")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    os.environ["EKBASIS_VERDICT_CACHE"] = "off"
    os.environ["EKBASIS_PSQL"] = PSQL
    with open(a.out, "w") as fh:
        for c in C:
            if a.only and c["id"] not in a.only:
                continue
            res = json.load(open(c["_res"]))
            base, head = res["base"], res["head"]
            db = "dv_" + c["id"].replace("-", "_")[:40]
            replica(c, base, db)
            rec = {"id": c["id"], "notes": None}
            for arm, su in (("R", f"postgresql://postgres@127.0.0.1:{PORT}/{db}"), ("N", None)):
                stub = Stub()
                v = M.check(os.path.join(c["_repos"], c["repo"]), base=base, head=head, globs=(glob_for(c["path"]),),
                            pg_url=ADMIN, stats_url=su, client=stub, psql=PSQL)
                f = next((x for x in v.files if x.path == c["path"]), None)
                rec[arm] = {"kind": f and f.kind, "decided": getattr(f, "decided", None), "state": f and f.state, "edited": getattr(f, "edited", None),
                            "facts": (f.state.split("\nFacts: ", 1)[1].split("\n\nActions", 1)[0]
                                      if f and "\nFacts: " in (f.state or "") else None)}
            X.drop_db(db)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(c["id"], "R:", rec["R"]["kind"], rec["R"]["decided"] and "DECIDED", "| facts:",
                  (rec["R"]["facts"] or "")[:300], flush=True)


if __name__ == "__main__":
    main()
