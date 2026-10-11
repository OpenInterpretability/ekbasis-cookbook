"""Runs INSIDE the project container (the project's Python). Actions, chosen by EKH_ACTION:
  plan    - every migration in apply order: {node, path, atomic}
  apply   - apply EKH_NODES (JSON list) in order on the database the environment points at; stop at the first error
Django: run as `python manage.py shell -c "exec(open('/tmp/ekh_inner.py').read())"`.
Alembic: run as `python /tmp/ekh_inner.py` with EKH_INI (the alembic.ini path).
Output: one line `EKBASIS-JSON:<json>`."""
import json
import os
import sys

MARK = "EKBASIS-JSON:"
ROOT = os.path.realpath(os.environ.get("EKH_ROOT", "/src/head"))
FW = os.environ["EKH_FRAMEWORK"]
ACTION = os.environ["EKH_ACTION"]


def rel(f):
    f = os.path.realpath(f)
    return os.path.relpath(f, ROOT).replace(os.sep, "/") if f.startswith(ROOT) else f


def django():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from django.db.migrations.loader import MigrationLoader
    if ACTION == "plan":
        loader = MigrationLoader(None, ignore_no_migrations=True)
        order, seen = [], set()
        for leaf in sorted(loader.graph.leaf_nodes()):
            for n in loader.graph.forwards_plan(leaf):
                if n not in seen:
                    seen.add(n)
                    order.append(n)
        out = []
        for n in order:
            mig = loader.graph.nodes[n]
            f = getattr(sys.modules.get(type(mig).__module__), "__file__", "") or ""
            out.append({"node": list(n), "path": rel(f), "atomic": bool(getattr(mig, "atomic", True)),
                        "replaces": bool(getattr(mig, "replaces", None))})
        return out
    if ACTION == "apply":
        ex = MigrationExecutor(connection)
        state = ex._create_project_state(with_applied_migrations=True)
        done = []
        for n in json.loads(os.environ["EKH_NODES"]):
            mig = ex.loader.graph.nodes[tuple(n)]
            try:
                state = ex.apply_migration(state, mig)
                done.append(n)
            except Exception as e:  # noqa: BLE001
                return {"done": done, "failed": n, "error": f"{type(e).__name__}: {e}"[:600]}
        return {"done": done, "failed": None, "error": None}
    raise SystemExit("unknown action")


def alembic():
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config(os.environ["EKH_INI"])
    if os.environ.get("EKH_VERSIONS"):
        cfg.set_main_option("version_locations", os.environ["EKH_VERSIONS"])
    if os.environ.get("EKH_SCRIPT_LOCATION"):  # Flask-Migrate sets it at run time (superset)
        cfg.set_main_option("script_location", os.environ["EKH_SCRIPT_LOCATION"])
    if os.environ.get("EKH_SET_URL"):          # projects whose env.py reads sqlalchemy.url (mlflow)
        cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    if ACTION == "plan":
        sd = ScriptDirectory.from_config(cfg)
        revs = list(sd.walk_revisions("base", "heads"))[::-1]
        out = []
        for r in revs:
            down = r.down_revision
            out.append({"node": [r.revision], "path": rel(r.path), "atomic": True,
                        "down": list(down) if isinstance(down, (list, tuple)) else ([down] if down else []),
                        "replaces": False})
        return out
    if ACTION == "apply":
        done = []
        for n in json.loads(os.environ["EKH_NODES"]):
            try:
                if os.environ.get("EKH_ANYIO"):          # prefect's env.py runs only inside an AnyIO worker thread
                    import anyio
                    from anyio import to_thread
                    anyio.run(to_thread.run_sync, lambda: command.upgrade(cfg, n[0]))
                else:
                    command.upgrade(cfg, n[0])
                done.append(n)
            except Exception as e:  # noqa: BLE001
                return {"done": done, "failed": n, "error": f"{type(e).__name__}: {e}"[:600]}
        return {"done": done, "failed": None, "error": None}
    raise SystemExit("unknown action")


if FW == "django":
    res = django()
elif os.environ.get("EKH_APP_FACTORY"):        # Flask apps whose migrations import the app (superset)
    import importlib
    mod, fn = os.environ["EKH_APP_FACTORY"].split(":")
    with getattr(importlib.import_module(mod), fn)().app_context():
        res = alembic()
else:
    res = alembic()
print(MARK + json.dumps(res))
