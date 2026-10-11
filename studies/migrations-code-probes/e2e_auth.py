import json, os, sys
from ekbasis import migrations as M
sys.path.insert(0, "ekb_new/tests")
from test_migrations import Fake
os.environ["EKBASIS_VERDICT_CACHE"] = "off"
PG = "postgresql://postgres@127.0.0.1:55493/postgres"; os.environ["EKBASIS_PSQL"] = "/opt/homebrew/opt/postgresql@16/bin/psql"
for setup in (None, "guard-setup.sql"):
    v = M.check("../real_cases/repos/auth", base="ekb-e2e-base", head="ekb-e2e-head", globs=("migrations/*.up.sql",), pg_url=PG, client=Fake(), setup_sql=setup)
    print("setup:", setup, "| notes:", [n[:400] for n in v.notes])
    for f in v.files: print("  ", f.path, f.kind, (f.reason or "")[:200], "| facts:", ("Facts:" in (f.state or "")))
