"""Desenvolvimento, sem modelo: os 34 casos reais (real_cases/results) reconstruídos como PR pelo produto, OLD (sem
corte) e NEW (corte), com um cliente falso que só guarda o estado. Lê os repositórios de real_cases sem escrever neles
(GIT_NO_LAZY_FETCH=1: nada é baixado; um blob ausente vira erro, não fetch)."""
import glob, json, os, sys
os.environ["GIT_NO_LAZY_FETCH"] = "1"
os.environ["EKBASIS_VERDICT_CACHE"] = "off"
sys.path.insert(0, "ekbasis")
from ekbasis import migrations as M
from ekbasis.client import Answer

RC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "real_cases")
PG = "postgresql://postgres@127.0.0.1:55497/postgres"
PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"


class Capture:
    url = "capture"

    def __init__(self):
        self.states = []

    def ask(self, state, questions, read_once=False, images=None):
        self.states.append(state)
        return {k: Answer(value=False, confidence=0.9, probabilities={"yes": 0.1, "no": 0.9}, p_yes=0.1) for k in questions}


def glob_for(path):
    folder, tool = M.set_dir(path), M.tool_of(path)
    return {"prisma": f"{folder}/*/migration.sql", "diesel": f"{folder}/*/up.sql",
            "golang-migrate": f"{folder}/*.up.sql"}.get(tool, f"{folder}/*.sql")


out = []
for p in sorted(glob.glob(os.path.join(RC, "results", "*.json"))):
    c = json.load(open(p))
    repo = os.path.join(RC, "repos", c["repo"])
    rec = {"id": c["id"]}
    for arm, prune in (("old", False), ("new", True)):
        M.PRUNE = prune
        try:
            v = M.check(repo, base=c["base"], head=c["head"], globs=(glob_for(c["path"]),), pg_url=PG, client=Capture(),
                        psql=PSQL)
            f = [x for x in v.files if x.path == c["path"]]
            f = f[0] if f else None
            rec[arm] = {"kind": f.kind if f else None, "chars": len(f.state) if f else 0, "shown": f.shown if f else None,
                        "notes": f.notes if f else None, "state": f.state if f else None}
        except Exception as e:
            rec[arm] = {"error": f"{type(e).__name__}: {e}"[:300]}
    out.append(rec)
    o, n = rec["old"], rec["new"]
    print(f"{c['id'][:40]:40s} old {o.get('kind') or o.get('error','')[:40]!s:16s} {o.get('chars',0):6d} | new "
          f"{n.get('kind') or n.get('error','')[:40]!s:16s} {n.get('chars',0):6d} {('; '.join(n.get('notes') or []))[:90]}",
          flush=True)
json.dump(out, open("data/dev_real.json", "w"))
