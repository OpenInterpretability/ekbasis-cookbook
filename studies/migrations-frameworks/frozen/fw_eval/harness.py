"""Framework eval (v4), steps 0-1, no model calls.

  frame   : start each project's container (code at a pinned commit or package version, dependencies installed), list
            its migrations in apply order, and draw the sample from the migrations' source text (strata A/B/C).
  build   : walk each project's migrations in order on a progress database (applied by the framework, no rows). At each
            sampled migration:
              PRODUCT side - render it with the product's own renderer (ekbasis.frameworks: Django sqlmigrate / Alembic
                offline), take the base schema with pg_dump of the progress database, and build what migrate-check
                --bundle would send (or the decision it would make in code), with planner statistics of the seeded copy;
              LABEL side - copy the progress database, seed it (the study's frozen seeder, 20 rows per table; the
                framework's bookkeeping tables are left as they are), run the migration WITH THE FRAMEWORK (RunPython
                and all, in its own transaction semantics), and label with the study's frozen labeler.
Output: data/frame.jsonl, data/sample.jsonl, data/items/<project>.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SP, "pr_study"))
sys.path.insert(0, os.path.join(SP, "mgfw"))

import pgexec as X                       # noqa: E402  study (frozen): seeder, snapshots, labeler
import statebuild as SB                  # noqa: E402
from ekbasis import frameworks as FW     # noqa: E402  product
from ekbasis import migrations as M      # noqa: E402

SEED = "20261011:v4"
PORT = 55600
X.DSN = f"host=127.0.0.1 port={PORT} user=postgres"
ADMIN = f"postgresql://postgres@127.0.0.1:{PORT}/postgres"
PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"
NET, PG = "ekeval-net", "ekeval-pg"
ROLE, ROLE_PW = "ekeval_role", "ekeval_pw"
CAPS = {"A": 25, "B": 10, "C": 5}
EXTRA_A = 45
BOOKKEEPING = {"django_migrations", "alembic_version"}
MARK = "EKBASIS-JSON:"

PY_SETUP = "set -e; apt-get update -qq >/dev/null; apt-get install -y -qq gcc git libpq5 libpq-dev >/dev/null 2>&1; "
PROJECTS = {
    "healthchecks": dict(framework="django", repo="fw/hc", workdir=".", image="python:3.12-slim",
                         setup=PY_SETUP + "apt-get install -y -qq libcurl4-openssl-dev libssl-dev >/dev/null 2>&1; "
                                          "pip install -q -r requirements.txt",
                         env={"DB": "postgres"}),
    "netbox": dict(framework="django", repo="fw/netbox", workdir="netbox", image="python:3.12-slim",
                   setup=PY_SETUP + "cd /src/head && pip install -q -r requirements.txt && "
                                    "cp /tmp/netbox_configuration.py netbox/netbox/configuration.py",
                   env={}, files={"/tmp/netbox_configuration.py": "netbox_configuration.py"}),
    "wagtail": dict(framework="django", repo="fw/wagtail", workdir="wagtail/test", image="python:3.12-slim",
                    setup=PY_SETUP + "cd /src/head && pip install -q -e '.[testing]' 'psycopg[binary]'",
                    env={"DATABASE_ENGINE": "django.db.backends.postgresql", "DJANGO_SETTINGS_MODULE":
                         "wagtail.test.settings"},
                    exclude=r"^wagtail/test/"),
    "airflow": dict(framework="alembic", package="apache-airflow==2.10.5", image="python:3.12-slim",
                    setup=PY_SETUP + "pip install -q 'apache-airflow[postgres]==2.10.5' --constraint "
                          "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.12.txt",
                    ini="/usr/local/lib/python3.12/site-packages/airflow/alembic.ini",
                    cwd="/usr/local/lib/python3.12/site-packages/airflow",
                    env={"AIRFLOW__DATABASE__SQL_ALCHEMY_CONN": "{url}", "AIRFLOW__CORE__LOAD_EXAMPLES": "False"}),
    "prefect": dict(framework="alembic", package="prefect==3.4.0", image="python:3.12-slim",
                    setup=PY_SETUP + "pip install -q 'prefect==3.4.0'",
                    ini="/usr/local/lib/python3.12/site-packages/prefect/server/database/alembic.ini",
                    cwd="/usr/local/lib/python3.12/site-packages/prefect/server/database",
                    env={"PREFECT_API_DATABASE_CONNECTION_URL": "{url_asyncpg}", "PREFECT_HOME": "/tmp/prefect",
                         "EKH_ANYIO": "1",
                         "EKH_VERSIONS": "/usr/local/lib/python3.12/site-packages/prefect/server/database/"
                                         "_migrations/versions/postgresql"}),
}

STRATA = {
    "django": (re.compile(r"\b(RemoveField|DeleteModel|AlterField|RenameField|RenameModel|RunPython|RunSQL|"
                          r"AlterModelTable)\b"),
               re.compile(r"\b(AddConstraint|AlterUniqueTogether|AddIndex|AlterIndexTogether)\b|AddField\((?:(?!null=True)"
                          r"(?!default=)[^)])*\)", re.S)),
    "alembic": (re.compile(r"\bop\.(drop_column|drop_table|alter_column|execute|get_bind|bulk_insert|rename_table)\b|"
                           r"batch_op\.(drop_column|alter_column)\b|\bsession\b", re.S),
                re.compile(r"nullable\s*=\s*False|create_unique_constraint|create_foreign_key|create_check_constraint|"
                           r"create_primary_key|unique\s*=\s*True")),
}


def sh(*a, check=True, input_bytes=None, timeout=3600):
    p = subprocess.run(list(a), input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{a[:3]} failed: {p.stderr.decode(errors='replace')[-800:]}")
    return p


def ctr(name):
    return f"ekeval-{name}"


def ensure_infra():
    if sh("docker", "network", "inspect", NET, check=False).returncode != 0:
        sh("docker", "network", "create", NET)
    if sh("docker", "inspect", PG, check=False).returncode != 0:
        sh("docker", "run", "-d", "--name", PG, "--network", NET, "-p", f"127.0.0.1:{PORT}:5432",
           "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:16", "-c", "fsync=off", "-c", "max_connections=200")
        for _ in range(60):
            if sh("docker", "exec", PG, "pg_isready", "-U", "postgres", "-q", check=False).returncode == 0:
                break
            time.sleep(1)
        time.sleep(2)
        sh("docker", "exec", PG, "psql", "-U", "postgres", "-qc",
           f"CREATE ROLE {ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '{ROLE_PW}'")


def start_project(name):
    cfg = PROJECTS[name]
    c = ctr(name)
    if sh("docker", "inspect", c, check=False).returncode == 0:
        return
    sh("docker", "run", "-d", "--name", c, "--network", NET, "--entrypoint", "sleep", cfg["image"], "infinity")
    if cfg.get("repo"):
        tar = sh("git", "-C", os.path.join(SP, cfg["repo"]), "archive", "--format=tar", "--prefix=src/head/", "HEAD").stdout
        sh("docker", "exec", "-i", c, "tar", "-x", "-C", "/", input_bytes=tar)
    else:
        sh("docker", "exec", c, "mkdir", "-p", "/src/head")
    sh("docker", "exec", "-i", c, "tar", "-x", "-C", "/", input_bytes=FW._client_tar())
    for dst, src in (cfg.get("files") or {}).items():
        sh("docker", "exec", "-i", c, "sh", "-c", f"cat > {dst}", input_bytes=open(os.path.join(HERE, src), "rb").read())
    sh("docker", "exec", "-i", c, "sh", "-c", "cat > /tmp/ekh_inner.py",
       input_bytes=open(os.path.join(HERE, "inner.py"), "rb").read())
    p = sh("docker", "exec", "-w", wd(name), c, "sh", "-c", cfg["setup"], check=False, timeout=7200)
    if p.returncode != 0:
        raise RuntimeError(f"setup {name} failed: {p.stderr.decode(errors='replace')[-1500:]}")


def wd(name):
    if PROJECTS[name].get("cwd"):
        return PROJECTS[name]["cwd"]
    w = PROJECTS[name].get("workdir", ".")
    return "/src/head" if w in (".", "") else "/src/head/" + w.strip("/")


def env_for(name, db):
    cfg = PROJECTS[name]
    url = f"postgresql://{ROLE}:{ROLE_PW}@{PG}:5432/{db}"
    e = {"DATABASE_URL": url, "DB_HOST": PG, "DB_PORT": "5432", "DB_NAME": db, "DB_USER": ROLE, "DB_PASSWORD": ROLE_PW,
         "DATABASE_HOST": PG, "DATABASE_PORT": "5432", "DATABASE_NAME": db, "DATABASE_USER": ROLE,
         "DATABASE_PASSWORD": ROLE_PW, "PGHOST": PG, "PGPORT": "5432", "PGDATABASE": db, "PGUSER": ROLE,
         "PGPASSWORD": ROLE_PW, "EKBASIS_DB_URL": url, "PYTHONPATH": "/opt/ekbasis_client", "EKH_ROOT": src_root(name),
         "EKH_FRAMEWORK": cfg["framework"], "EKH_INI": cfg.get("ini", ""), "PYTHONDONTWRITEBYTECODE": "1"}
    for k, v in (cfg.get("env") or {}).items():
        e[k] = v.replace("{url_asyncpg}", url.replace("postgresql://", "postgresql+asyncpg://", 1)).replace("{url}", url)
    return e


def src_root(name):
    cfg = PROJECTS[name]
    return "/src/head" if cfg.get("repo") else "/usr/local/lib/python3.12/site-packages"


def inner(name, db, action, nodes=None, timeout=3600):
    cfg = PROJECTS[name]
    e = env_for(name, db)
    e["EKH_ACTION"] = action
    if nodes is not None:
        e["EKH_NODES"] = json.dumps(nodes)
    eargs = [x for k, v in e.items() for x in ("-e", f"{k}={v}")]
    if cfg["framework"] == "django":
        cmd = ["python", "manage.py", "shell", "-c", "exec(open('/tmp/ekh_inner.py').read())"]
    else:
        cmd = ["python", "/tmp/ekh_inner.py"]
    p = sh("docker", "exec", *eargs, "-w", wd(name), ctr(name), *cmd, check=False, timeout=timeout)
    lines = [l for l in p.stdout.decode(errors="replace").splitlines() if l.startswith(MARK)]
    if not lines:
        raise RuntimeError(f"inner {action} failed: {p.stderr.decode(errors='replace')[-1500:]}")
    return json.loads(lines[-1][len(MARK):])


def render(name, db, path):
    """The product's renderer, as migrate-gen runs it at the head tree."""
    cfg = PROJECTS[name]
    e = env_for(name, db)
    e["EKBASIS_PATHS"] = json.dumps([path])
    e["EKBASIS_ROOT"] = src_root(name)
    eargs = [x for k, v in e.items() for x in ("-e", f"{k}={v}")]
    if cfg["framework"] == "django":
        cmd = ["python", "manage.py", "shell", "-c", "from ekbasis.frameworks import django_main; django_main()"]
    else:
        command = f"alembic -c {cfg['ini']}"
        cmd = ["python", "-c", "import json, os; from ekbasis.frameworks import alembic_main; "
               f"alembic_main(json.loads(os.environ['EKBASIS_PATHS']), os.environ['EKBASIS_ROOT'], {command!r})"]
    p = sh("docker", "exec", *eargs, "-w", wd(name), ctr(name), *cmd, check=False, timeout=1800)
    lines = [l for l in p.stdout.decode(errors="replace").splitlines() if l.startswith(MARK)]
    if not lines:
        return {"path": path, "sql": "", "transaction": True, "python_ops": [], "error":
                "render crashed: " + p.stderr.decode(errors="replace").strip()[-300:]}
    recs = json.loads(lines[-1][len(MARK):])
    return recs[0] if recs else {"path": path, "sql": "", "transaction": True, "python_ops": [], "error": "no output"}


def read_source(name, path):
    cfg = PROJECTS[name]
    if cfg.get("repo") and not path.startswith("/"):
        return open(os.path.join(SP, cfg["repo"], path), encoding="utf-8", errors="replace").read()
    if path.startswith("/"):
        return sh("docker", "exec", ctr(name), "cat", path).stdout.decode(errors="replace")
    return sh("docker", "exec", ctr(name), "cat", os.path.join(src_root(name), path)).stdout.decode(errors="replace")


def stratum(fw, text):
    a, b = STRATA[fw]
    return "A" if a.search(text) else ("B" if b.search(text) else "C")


# ---------------------------------------------------------------- frame and sample (text only)

def frame(names=None):
    ensure_infra()
    out, sample = [], []
    for name in names or list(PROJECTS):
        cfg = PROJECTS[name]
        start_project(name)
        db = "plan_" + name
        nodes = inner(name, "postgres", "plan")
        excl = re.compile(cfg["exclude"]) if cfg.get("exclude") else None
        firsts = set()
        recs = []
        for i, n in enumerate(nodes):
            text = read_source(name, n["path"])
            first = False
            if cfg["framework"] == "django":
                first = bool(re.search(r"^\s*initial\s*=\s*True", text, re.M)) or n["path"].endswith("0001_initial.py")
            else:
                first = not n.get("down")
            r = {"project": name, "framework": cfg["framework"], "idx": i, "node": n["node"], "path": n["path"],
                 "sha256": hashlib.sha256(text.encode()).hexdigest(), "stratum": stratum(cfg["framework"], text),
                 "eligible": not first and not n.get("replaces") and not (excl and excl.search(n["path"]))
                             and not n["path"].startswith("/")}
            recs.append(r)
        out += recs
        rng = random.Random(f"{SEED}:{name}")
        pick = []
        for st in "ABC":
            pool = sorted([r for r in recs if r["eligible"] and r["stratum"] == st], key=lambda r: r["idx"])
            pick += rng.sample(pool, min(CAPS[st], len(pool)))
        # extension drawn before any model call, after a first build showed few positives: 45 more from stratum A
        rest = sorted([r for r in recs if r["eligible"] and r["stratum"] == "A" and r not in pick], key=lambda r: r["idx"])
        pick += random.Random(f"{SEED}:{name}:extra").sample(rest, min(EXTRA_A, len(rest)))
        sample += sorted(pick, key=lambda r: r["idx"])
        by = {st: sum(1 for r in pick if r["stratum"] == st) for st in "ABC"}
        print(f"{name}: {len(recs)} migrations, eligible {sum(r['eligible'] for r in recs)}, sampled {len(pick)} {by}",
              flush=True)
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    with open(os.path.join(HERE, "data", "frame.jsonl"), "w") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(HERE, "data", "sample.jsonl"), "w") as f:
        for r in sample:
            f.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------- build: labels and product states

def admin(sql):
    with X.admin() as a:
        a.execute(sql)


def create_role_db(db, template=None):
    X.drop_db(db)
    admin(f'CREATE DATABASE "{db}" OWNER {ROLE}' + (f' TEMPLATE "{template}"' if template else ""))


def pg_dump(db):
    return sh("docker", "exec", PG, "pg_dump", "-U", "postgres", "--schema-only", "--no-owner", "--no-privileges",
              "--no-comments", db).stdout.decode(errors="replace")


def strip_bookkeeping(snap):
    snap = dict(snap)
    snap["tables"] = {k: v for k, v in snap["tables"].items() if k.split(".")[-1] not in BOOKKEEPING}
    return snap


def product_side(name, rec, base_schema, base_incomplete, stats):
    """What `migrate-check --bundle` decides before asking the model, and the state it sends (mirrors check_bundle
    and _check_file at the product commit)."""
    fw = PROJECTS[name]["framework"]
    sql = rec.get("sql") or ""
    tx0 = bool(rec.get("transaction", True))
    out = {"transaction": tx0, "decided": None, "schema_error": None, "python_ops": rec.get("python_ops") or [],
           "render_error": rec.get("error")}
    if rec.get("error"):
        out["decided"] = "cannot_foresee_render"
        return out
    if rec.get("python_ops"):
        out["decided"] = "cannot_foresee_code"
        return out
    stmts = M.split_sql(sql)
    if not stmts:
        out["decided"] = "ok_empty"
        return out
    tx = M._transaction_for(fw, stmts, not tx0, [])
    out["transaction"] = tx
    with M.Scratch(ADMIN, PSQL) as sc:
        err = sc.db.apply(base_schema, transaction=False)
        dirty = bool(base_incomplete) or bool(err and not re.search(
            r'schema "public" already exists|must be owner of|permission denied to set', err))
        probe = sc.clone()
        try:
            e = probe.apply(sql, transaction=tx)
            code = probe.last_sqlstate
        finally:
            sc.drop(probe)
        if e and M.needs_privilege(code, e):
            out.update(decided="cannot_foresee_privilege", schema_error=e)
            return out
        if e and dirty:
            out.update(decided="cannot_foresee_base", schema_error=e)
            return out
        if e and tx:
            out.update(decided="schema", schema_error=e)
            return out
        facts = [f"Run on this schema with no rows, the migration fails: {e}."] if e else []
        out["schema_error"] = e
        out["state"], out["shown"] = M.build_state(sc.db.json(M.CATALOG) or {}, stmts, stats, fw, tx, facts)
        if len(out["state"]) > M.MAX_CHARS:
            out["decided"] = "cannot_foresee_long"
    return out


def build(name):
    ensure_infra()
    start_project(name)
    sample = [json.loads(l) for l in open(os.path.join(HERE, "data", "sample.jsonl"))]
    want = {r["idx"]: r for r in sample if r["project"] == name}
    allnodes = [json.loads(l) for l in open(os.path.join(HERE, "data", "frame.jsonl"))]
    nodes = [r for r in allnodes if r["project"] == name]
    P = f"prog_{name}"
    create_role_db(P)
    out_path = os.path.join(HERE, "data", "items", f"{name}.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pending, broken = [], None
    t0 = time.time()
    with open(out_path, "w") as f:
        for r in nodes:
            if r["idx"] not in want:
                pending.append(r["node"])
                continue
            if pending:
                res = inner(name, P, "apply", pending)
                if res["error"] and not broken:
                    broken = f"{res['failed']}: {res['error'][:200]}"
                pending = []
            rec = dict(want[r["idx"]])
            try:
                rec.update(item(name, r, P, broken))
            except Exception as e:  # noqa: BLE001
                rec.update(excluded=["harness_error"], harness_error=f"{type(e).__name__}: {e}"[:600],
                           tb=traceback.format_exc()[-1500:])
            f.write(json.dumps(rec, default=str) + "\n")
            f.flush()
            res = inner(name, P, "apply", [r["node"]])
            if res["error"] and not broken:
                broken = f"{res['failed']}: {res['error'][:200]}"
            print(f"{name} {r['path']} {rec.get('label')} {rec.get('product', {}).get('decided')} "
                  f"{rec.get('excluded')} {round(time.time() - t0)}s", flush=True)
    X.drop_db(P)


def item(name, r, P, broken):
    fw = PROJECTS[name]["framework"]
    out = {"progress_broken": broken}
    base_schema = pg_dump(P)
    rend = render(name, P, r["path"])
    out["render"] = {k: rend.get(k) for k in ("sql", "transaction", "python_ops", "error", "name")}
    # label side: seeded copy, the framework runs the migration
    S = f"seed_{name}"
    create_role_db(S, template=P)
    out["seeded_rows"] = X.seed(S, random.Random(f"{SEED}:{name}:{r['path']}"))
    with X.connect(S) as c:
        c.execute("SET session_replication_role = replica")
        if fw == "django":
            c.execute("DELETE FROM django_migrations WHERE app LIKE 'zq%' OR name LIKE 'zq%'")
        else:
            c.execute("DELETE FROM alembic_version WHERE version_num LIKE 'zq%'")
    pg = M.Pg(f"postgresql://postgres@127.0.0.1:{PORT}/{S}", PSQL)
    pg.run(["-c", "ANALYZE"])
    stats = pg.json(M.STATS)
    sql_stmts = M.split_sql(rend.get("sql") or "")
    with X.connect(S) as cc:
        cat = X.catalog(cc)
    named = [t["name"] for t in cat["tables"].values()
             if re.search(r"(?<![\w$])\"?" + re.escape(t["name"]) + r"\"?(?![\w$])", "\n".join(sql_stmts), re.I)]
    pre = X.snapshot(S)
    res = inner(name, S, "apply", [r["node"]])
    post = X.snapshot(S)
    L = X.loss_label(strip_bookkeeping(pre), strip_bookkeeping(post))
    out["label"] = {"lost": L["lost"], "fails": bool(res["error"])}
    out["run_error"] = res["error"]
    out["lost_detail"] = L["lost_detail"][:10]
    X.drop_db(S)
    out["product"] = product_side(name, rend, base_schema, bool(broken), stats)
    ex = []
    if broken:
        ex.append("progress_broken")
    if any(out["seeded_rows"].get(t, 0) == 0 for t in named if t in out["seeded_rows"]):
        ex.append("named_table_not_seeded")
    if any(t in named for t in L["untracked_tables"]):
        ex.append("untracked_rows")
    out["excluded"] = ex
    return out


if __name__ == "__main__":
    if sys.argv[1] == "frame":
        frame(sys.argv[2:] or None)
    elif sys.argv[1] == "start":
        ensure_infra()
        for n in sys.argv[2:] or list(PROJECTS):
            t0 = time.time()
            try:
                start_project(n)
                print(n, "ready", round(time.time() - t0), "s", flush=True)
            except Exception as e:  # noqa: BLE001
                print(n, "FAILED", str(e)[-600:], flush=True)
    elif sys.argv[1] == "build":
        for n in sys.argv[2:] or list(PROJECTS):
            build(n)
