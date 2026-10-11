"""Framework eval v5 (on-code warn): the v4 harness (frozen, ../fw_eval/harness.py) with new projects, a new seed, and
an apply command for projects whose env.py needs their own CLI (Superset). Steps and outputs as in v4."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "fw_eval"))
import harness as H   # noqa: E402

H.HERE = HERE
H.SEED = "20261011:v5"
PY = H.PY_SETUP
H.PROJECTS = {
    "saleor": dict(framework="django", repo="fw/saleor", workdir=".", image="python:3.12-slim",
                   setup=PY + "apt-get install -y -qq libmagic1 >/dev/null 2>&1; cd /src/head && pip install -q -e . pytest",
                   env={"SECRET_KEY": "eval-only", "ALLOWED_HOSTS": "*", "ALLOWED_CLIENT_HOSTS": "localhost", "DEBUG": "True"}),
    "babybuddy": dict(framework="django", repo="fw/babybuddy", workdir=".", image="python:3.12-slim",
                      setup=PY + "pip install -q -r requirements.txt",
                      env={"SECRET_KEY": "eval-only", "DJANGO_SETTINGS_MODULE": "babybuddy.settings.base"}),
    "paperless": dict(framework="django", repo="fw/paperless", workdir="src", image="python:3.12-slim",
                      setup=PY + "apt-get install -y -qq libmagic1 >/dev/null 2>&1; cd /src/head && pip install -q -e . "
                                 "'psycopg[binary]'",
                      env={"PAPERLESS_DBENGINE": "postgresql", "PAPERLESS_DBHOST": "{host}", "PAPERLESS_DBNAME": "{db}",
                           "PAPERLESS_DBUSER": "{user}", "PAPERLESS_DBPASS": "{pw}", "PAPERLESS_SECRET_KEY": "eval-only"}),
    "mlflow": dict(framework="alembic", package="mlflow", image="python:3.12-slim",
                   setup=PY + "pip install -q 'mlflow==3.1.0' 'psycopg2-binary' 'psycopg[binary]'",
                   ini="/tmp/mlflow_alembic.ini", cwd="/tmp", env={"EKH_SET_URL": "1"},
                   files={"/tmp/mlflow_alembic.ini": "mlflow_alembic.ini"}),
    "superset": dict(framework="alembic", package="apache-superset", image="python:3.11-slim",
                     setup=PY + "apt-get update -qq >/dev/null; apt-get install -y -qq g++ cargo >/dev/null 2>&1; pip install -q 'apache-superset==4.1.2' 'psycopg2-binary' 'marshmallow<4'",
                     ini="/usr/local/lib/python3.11/site-packages/superset/migrations/alembic.ini",
                     cwd="/tmp",
                     site="/usr/local/lib/python3.11/site-packages",
                     env={"SUPERSET_CONFIG_PATH": "/tmp/superset_config.py", "FLASK_APP": "superset",
                          "EKH_SCRIPT_LOCATION": "/usr/local/lib/python3.11/site-packages/superset/migrations",
                          "EKH_APP_FACTORY": "superset.app:create_app"},
                     files={"/tmp/superset_config.py": "superset_config.py"},
                     apply_cmd="superset db upgrade {rev}", render_cmd="superset db"),
}

_env_for = H.env_for


def env_for(name, db):
    e = _env_for(name, db)
    for k, v in list(e.items()):
        if isinstance(v, str):
            e[k] = (v.replace("{host}", H.PG).replace("{db}", db).replace("{user}", H.ROLE)
                    .replace("{pw}", H.ROLE_PW))
    if name == "mlflow":
        e["MLFLOW_EVAL_URL"] = e["DATABASE_URL"]
    return e


H.env_for = env_for
_src_root = H.src_root


def src_root(name):
    cfg = H.PROJECTS[name]
    if cfg.get("site"):
        return cfg["site"]
    return _src_root(name)


H.src_root = src_root
_inner = H.inner


def inner(name, db, action, nodes=None, timeout=3600):
    cfg = H.PROJECTS[name]
    if action == "apply" and cfg.get("apply_cmd"):
        e = H.env_for(name, db)
        eargs = [x for k, v in e.items() for x in ("-e", f"{k}={v}")]
        done = []
        for n in nodes or []:
            p = H.sh("docker", "exec", *eargs, "-w", H.wd(name), H.ctr(name), "sh", "-c",
                     cfg["apply_cmd"].format(rev=n[0]), check=False, timeout=timeout)
            if p.returncode != 0:
                return {"done": done, "failed": n, "error": p.stderr.decode(errors="replace").strip()[-600:]}
            done.append(n)
        return {"done": done, "failed": None, "error": None}
    if action == "plan":                       # a role-owned empty database (Superset's app connects at import)
        db = f"plan_{name}"
        H.create_role_db(db)
    return _inner(name, db, action, nodes, timeout)


H.inner = inner
_render = H.render


def render(name, db, path):
    cfg = H.PROJECTS[name]
    if cfg.get("render_cmd"):
        e = H.env_for(name, db)
        e["EKBASIS_PATHS"] = json.dumps([path])
        e["EKBASIS_ROOT"] = H.src_root(name)
        eargs = [x for k, v in e.items() for x in ("-e", f"{k}={v}")]
        cmd = ["python", "-c", "import json, os; from ekbasis.frameworks import alembic_main; "
               f"alembic_main(json.loads(os.environ['EKBASIS_PATHS']), os.environ['EKBASIS_ROOT'], {cfg['render_cmd']!r})"]
        p = H.sh("docker", "exec", *eargs, "-w", H.wd(name), H.ctr(name), *cmd, check=False, timeout=1800)
        lines = [l for l in p.stdout.decode(errors="replace").splitlines() if l.startswith(H.MARK)]
        if not lines:
            return {"path": path, "sql": "", "transaction": True, "python_ops": [], "error":
                    "render crashed: " + p.stderr.decode(errors="replace").strip()[-300:]}
        recs = json.loads(lines[-1][len(H.MARK):])
        return recs[0] if recs else {"path": path, "sql": "", "transaction": True, "python_ops": [], "error": "no output"}
    return _render(name, db, path)


H.render = render

# MLflow builds its first tables with SQLAlchemy (initial_models) before its first Alembic revision, as
# mlflow.store.db.utils._initialize_tables does; the progress database gets the same start.
_create = H.create_role_db
INIT = {"mlflow": "from sqlalchemy import create_engine; import os; from mlflow.store.tracking.dbmodels.initial_models import Base; "
                  "Base.metadata.create_all(create_engine(os.environ['DATABASE_URL']))"}


def create_role_db(db, template=None):
    _create(db, template)
    for name, code in INIT.items():
        if db == f"prog_{name}" and template is None:
            e = H.env_for(name, db)
            eargs = [x for k, v in e.items() for x in ("-e", f"{k}={v}")]
            H.sh("docker", "exec", *eargs, H.ctr(name), "python", "-c", code)


H.create_role_db = create_role_db

EXTRA2 = {"saleor": 150, "superset": 150}


def extend():
    """Second extension, drawn before any model call after the first build showed few positives among the migrations
    the product answers: more stratum-A migrations from the two largest projects."""
    import random
    frame = [json.loads(l) for l in open(os.path.join(HERE, "data", "frame.jsonl"))]
    sample = [json.loads(l) for l in open(os.path.join(HERE, "data", "sample.jsonl"))]
    have = {(r["project"], r["path"]) for r in sample}
    for name, k in EXTRA2.items():
        pool = sorted([r for r in frame if r["project"] == name and r["eligible"] and r["stratum"] == "A"
                       and (name, r["path"]) not in have], key=lambda r: r["idx"])
        sample += random.Random(f"{H.SEED}:{name}:extra2").sample(pool, min(k, len(pool)))
    sample.sort(key=lambda r: (r["project"], r["idx"]))
    with open(os.path.join(HERE, "data", "sample.jsonl"), "w") as f:
        for r in sample:
            f.write(json.dumps(r) + "\n")
    print(len(sample))


if __name__ == "__main__":
    if sys.argv[1] == "extend":
        extend()
        sys.exit()
    if sys.argv[1] == "frame":
        H.frame(sys.argv[2:] or None)
    elif sys.argv[1] == "start":
        H.ensure_infra()
        for n in sys.argv[2:] or list(H.PROJECTS):
            try:
                H.start_project(n)
                print(n, "ready", flush=True)
            except Exception as ex:  # noqa: BLE001
                print(n, "FAILED", str(ex)[-800:], flush=True)
    elif sys.argv[1] == "build":
        for n in sys.argv[2:] or list(H.PROJECTS):
            H.build(n)
