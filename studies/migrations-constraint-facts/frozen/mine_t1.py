"""v4 T1 step 1: the real_cases mining (same signals) on the 12 test repositories, restricted to their PostgreSQL
migration folders (PREREG_v4 3.2), strong-signal commits newest first, at most 25 per repository."""
import glob, json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, glob.glob(os.path.join(os.path.dirname(HERE), "real_cases/venv/lib/python*/site-packages"))[0])
from ekbasis.migrations import is_migration
FOLDERS = {
    "windmill": ["backend/migrations/"],
    "sourcegraph-public-snapshot": ["migrations/frontend/", "migrations/codeintel/", "migrations/codeinsights/"],
    "harness": ["app/store/database/migrate/postgres/"],
    "ente": ["server/migrations/"],
    "openmeter": ["tools/migrate/migrations/"],
    "inbox-zero": ["apps/web/prisma/migrations/"],
    "linkwarden": ["packages/prisma/migrations/"],
    "openpanel": ["packages/db/prisma/migrations/"],
    "teable": ["packages/db-main-prisma/prisma/postgres/migrations/"],
    "authelia": ["internal/storage/migrations/postgres/"],
    "storage": ["migrations/tenant/", "migrations/multitenant/"],
    "atuin": ["crates/atuin-server/src/db/postgres/migrations/", "crates/atuin-server-postgres/migrations/"],
}
MSG = re.compile(r"revert|hotfix|hot-fix|rollback|roll back|broke|broken|fail|data loss|lost|not null|constraint|"
                 r"duplicate|unique|deadlock|lock|timeout|downtime|incident|outage|\bfix|repair|restore|undo|corrupt|"
                 r"wrong|bad migration|prod", re.I)
NAME = re.compile(r"fix|revert|repair|hotfix|correct|restore|undo|rollback|dedup|cleanup|backfill", re.I)
STRONG = re.compile(r"revert|hotfix|rollback|roll back|broke|broken|fail|data loss|lost|not null|constraint|duplicate|"
                    r"unique|deadlock|lock|timeout|downtime|incident|outage|corrupt|wrong|prod|(fix.*migrat)|(migrat.*fix)", re.I)
out = []
for r, folders in FOLDERS.items():
    p = os.path.join(HERE, "repos", r)
    log = subprocess.run(["git", "-C", p, "log", "--first-parent", "--no-renames", "--name-status",
                          "--format=%x00%H%x09%P%x09%aI%x09%s"], capture_output=True, text=True, errors="replace").stdout
    n = 0
    for blk in log.split("\x00")[1:]:
        lines = blk.strip("\n").split("\n")
        h, par, date, subj = (lines[0].split("\t") + ["", "", "", ""])[:4]
        files = [l.split("\t") for l in lines[1:] if "\t" in l]
        mig = [(s, f) for s, f in files if any(f.startswith(d) for d in folders) and f.endswith(".sql")
               and not f.endswith("down.sql")]
        if not mig:
            continue
        added = [f for s, f in mig if s == "A"]; mod = [f for s, f in mig if s == "M"]; dele = [f for s, f in mig if s == "D"]
        sig = []
        if MSG.search(subj): sig.append("msg")
        if mod: sig.append("edit")
        if dele: sig.append("delete")
        if any(NAME.search(f) for f in added): sig.append("name")
        if sig and STRONG.search(subj):
            out.append(dict(repo=r, sha=h, date=date[:10], subj=subj, added=added, modified=mod, deleted=dele, signals=sig))
            n += 1
            if n >= 25:
                break
json.dump(out, open(os.path.join(HERE, "mined_t1.json"), "w"), indent=0)
import collections
print(len(out), collections.Counter(o["repo"] for o in out))
