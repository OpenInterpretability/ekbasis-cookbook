"""Rails eval v7: the v6 harness (../../fw_eval_rails/harness_rails.py, itself on the frozen v4 harness) with NEW
projects, a new seed, the product at the v7 commit (ekbasis clone in ../ekbasis), a pgvector-capable scratch
PostgreSQL (Chatwoot), and a Redis reachable by the PRODUCT side too (the product now starts one on the generator's
network when the Gemfile needs it; here both sides use the eval network's Redis).

Excluded before the sample was drawn: Chatwoot. Its history does not replay from an empty database with the current
code (migration 20231211010807 stops at "uninitialized constant ActsAsTaggableOn::Taggable::Cache" after 23 of 192).

Added after the first two builds showed few risky migrations among those the product answers (Redmine: 4 of 58), and
before any model call: Consul Democracy, every eligible migration of stratum A plus the usual caps of B and C, drawn
with its own seed (`frame_ext`). Excluded before that draw: Loomio, whose history does not replay from an empty
database (540 of its 1089 migrations inherit from the unversioned ActiveRecord::Migration, which Rails 8 refuses);
Discourse, whose migrations need its post-deploy split and plugins (not attempted).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(SP, "fw_eval_rails"))
import harness_rails as HR      # noqa: E402  (v6 overrides; imports the frozen v4 harness)
H = HR.H
# the product under test: the v7 clone, not the v4/v5 checkout
for m in [k for k in list(sys.modules) if k == "ekbasis" or k.startswith("ekbasis.")]:
    del sys.modules[m]
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ekbasis"))
from ekbasis import frameworks as FW     # noqa: E402
from ekbasis import migrations as M      # noqa: E402
H.M, H.FW, HR.M, HR.FW = M, FW, M, FW
assert "schema_only_plan" in dir(M), "wrong ekbasis on the path"

H.HERE = HR.HERE = HERE
H.SEED = "20261011:v7"
H.PORT = 55601
H.X.DSN = f"host=127.0.0.1 port={H.PORT} user=postgres"
H.ADMIN = f"postgresql://postgres@127.0.0.1:{H.PORT}/postgres"
H.NET, H.PG = "ekeval7-net", "ekeval7-pg"
H.ctr = lambda name: f"ekeval7-{name}"
RB = HR.RB_SETUP
ENV = HR.COMMON_ENV
H.PROJECTS = {
    "redmine": dict(framework="rails", repo="fw/redmine", workdir=".", image="ruby:3.4",
                    setup=RB + "cp /tmp/redmine_database.yml config/database.yml && bundle config set --local without "
                               "'test' && bundle install --quiet",
                    env=dict(ENV), files={"/tmp/redmine_database.yml": "redmine_database.yml"}),
    "openproject": dict(framework="rails", repo="fw/openproject", workdir=".", image="ruby:4.0.7",
                        setup=RB + "cp /tmp/openproject_database.yml config/database.yml && bundle config set --local "
                                   "without 'test' && bundle install --quiet",
                        env=dict(ENV, REDIS_URL="redis://ekeval7-redis:6379", OPENPROJECT_HTTPS="false"),
                        files={"/tmp/openproject_database.yml": "openproject_database.yml"}),
    "consuldemocracy": dict(framework="rails", repo="fw/consuldemocracy", workdir=".", image="ruby:3.4.11",
                            setup=RB + "apt-get install -y -qq nodejs cmake pkg-config >/dev/null 2>&1; cp config/database.yml.example "
                                       "config/database.yml && cp config/secrets.yml.example config/secrets.yml 2>/dev/null; "
                                       "bundle config set --local without 'test' && bundle install --quiet",
                            env=dict(ENV)),
}

# The product's generator now has a Redis when the Gemfile needs one (--redis auto): the render side keeps REDIS_URL
_render = HR.render


def render(name, db, path):
    R = f"render_{name}"
    H.create_role_db(R, template=db)
    try:
        e = H.env_for(name, R)
        e["EKBASIS_PATHS"] = json.dumps([path])
        e["EKBASIS_ROOT"] = H.src_root(name)
        eargs = [x for k, v in e.items() for x in ("-e", f"{k}={v}")]
        p = H.sh("docker", "exec", *eargs, "-w", H.wd(name), H.ctr(name), "bin/rails", "runner",
                 "/tmp/ekbasis_rails.rb", check=False, timeout=1800)
        lines = [l for l in p.stdout.decode(errors="replace").splitlines() if l.startswith(H.MARK)]
        if not lines:
            return {"path": path, "sql": "", "transaction": True, "python_ops": [], "error":
                    "render crashed: " + p.stderr.decode(errors="replace").strip()[-300:]}
        recs = json.loads(lines[-1][len(H.MARK):])
        rec = recs[0] if recs else {"path": path, "sql": "", "transaction": True, "python_ops": [], "error": "no output"}
        rec["python_ops"] = FW.rails_ruby_ops(H.read_source(name, path))
        return rec
    finally:
        H.X.drop_db(R)


H.render = HR.render = render

# a pgvector-capable scratch PostgreSQL; Chatwoot's untrusted extensions are created by the superuser in the progress
# database (as an operator would before deploying), the migrations still run as the non-superuser role
_ensure = H.ensure_infra


def ensure_infra():
    if H.sh("docker", "network", "inspect", H.NET, check=False).returncode != 0:
        H.sh("docker", "network", "create", H.NET)
    if H.sh("docker", "inspect", "ekeval7-redis", check=False).returncode != 0:
        H.sh("docker", "run", "-d", "--name", "ekeval7-redis", "--network", H.NET, "redis:7-alpine")
    if H.sh("docker", "inspect", H.PG, check=False).returncode != 0:
        H.sh("docker", "run", "-d", "--name", H.PG, "--network", H.NET, "-p", f"127.0.0.1:{H.PORT}:5432",
             "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "pgvector/pgvector:pg16", "-c", "fsync=off",
             "-c", "max_connections=200")
        import time
        for _ in range(60):
            if H.sh("docker", "exec", H.PG, "pg_isready", "-U", "postgres", "-q", check=False).returncode == 0:
                break
            time.sleep(1)
        time.sleep(2)
        H.sh("docker", "exec", H.PG, "psql", "-U", "postgres", "-qc",
             f"CREATE ROLE {H.ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '{H.ROLE_PW}'")


H.ensure_infra = ensure_infra
_create = H.create_role_db
SUPER_EXT = {"chatwoot": ["vector", "pg_stat_statements"]}


def create_role_db(db, template=None):
    _create(db, template)
    for name, exts in SUPER_EXT.items():
        if db in (f"prog_{name}", f"plan_{name}") and template is None:
            for x in exts:
                H.sh("docker", "exec", H.PG, "psql", "-U", "postgres", "-d", db, "-qc", f'CREATE EXTENSION IF NOT EXISTS "{x}"')


H.create_role_db = create_role_db


# ---------------------------------------------------------------- one Rails boot per sampled migration
import random  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402

_start7 = H.start_project


def start_project(name):
    _start7(name)
    H.sh("docker", "exec", "-i", H.ctr(name), "sh", "-c", "cat > /tmp/ekh_item.rb",
         input_bytes=open(os.path.join(HERE, "ekh_item.rb"), "rb").read())
    H.sh("docker", "exec", "-i", H.ctr(name), "sh", "-c", "cat > /tmp/ekbasis_rails.rb", input_bytes=FW.RAILS_SCRIPT.encode())


H.start_project = start_project


def url(db):
    return f"postgresql://{H.ROLE}:{H.ROLE_PW}@{H.PG}:5432/{db}"


def boot(name, P, R, S, node, path, pending):
    e = H.env_for(name, P)
    e.update({"EKH_RENDER_URL": url(R), "EKH_LABEL_URL": url(S), "EKH_PROG_URL": url(P), "EKH_NODE": node[0],
              "EKH_PENDING": json.dumps([n[0] for n in pending]), "EKBASIS_PATHS": json.dumps([path]),
              "EKBASIS_ROOT": H.src_root(name)})
    eargs = [x for k, v in e.items() for x in ("-e", f"{k}={v}")]
    p = H.sh("docker", "exec", *eargs, "-w", H.wd(name), H.ctr(name), "bin/rails", "runner", "/tmp/ekh_item.rb",
             check=False, timeout=3600)
    lines = [l for l in p.stdout.decode(errors="replace").splitlines() if l.startswith(H.MARK)]
    if not lines:
        raise RuntimeError("item boot failed: " + p.stderr.decode(errors="replace")[-1500:])
    return json.loads(lines[-1][len(H.MARK):])


def build(name):
    """As harness.build, with one Rails boot per sampled migration (render, label and progress in one process)."""
    H.ensure_infra()
    H.start_project(name)
    sample = [json.loads(l) for l in open(os.path.join(HERE, "data", "sample.jsonl"))]
    want = {r["idx"]: r for r in sample if r["project"] == name}
    nodes = [json.loads(l) for l in open(os.path.join(HERE, "data", "frame.jsonl"))]
    nodes = [r for r in nodes if r["project"] == name]
    P, R, S = f"prog_{name}", f"render_{name}", f"seed_{name}"
    H.create_role_db(P)
    out_path = os.path.join(HERE, "data", "items", f"{name}.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if os.path.exists(os.path.join(HERE, "data", "inputs", f"{name}.jsonl")):
        os.remove(os.path.join(HERE, "data", "inputs", f"{name}.jsonl"))
    order = [i for i, r in enumerate(nodes) if r["idx"] in want]
    first = order[0] if order else len(nodes)
    broken = None
    if first:
        res = H.inner(name, P, "apply", [r["node"] for r in nodes[:first]])
        if res["error"]:
            broken = f"{res['failed']}: {res['error'][:200]}"
    t0 = time.time()
    with open(out_path, "w") as f:
        for j, i in enumerate(order):
            r = nodes[i]
            nxt = order[j + 1] if j + 1 < len(order) else len(nodes)
            pending = [x["node"] for x in nodes[i + 1:nxt]]
            rec = dict(want[r["idx"]])
            try:
                rec.update(item_fast(name, r, P, R, S, broken, pending))
                if rec.get("progress_error") and not broken:
                    broken = rec["progress_error"]
            except Exception as ex:  # noqa: BLE001
                rec.update(excluded=["harness_error"], harness_error=f"{type(ex).__name__}: {ex}"[:600],
                           tb=traceback.format_exc()[-1500:])
                for d in (R, S):
                    H.X.drop_db(d)
                res = H.inner(name, P, "apply", [r["node"]] + pending)
                if res["error"] and not broken:
                    broken = f"{res['failed']}: {res['error'][:200]}"
            f.write(json.dumps(rec, default=str) + "\n")
            f.flush()
            print(f"{name} {r['path']} {rec.get('label')} {rec.get('product', {}).get('decided')} {rec.get('excluded')} "
                  f"{round(time.time() - t0)}s", flush=True)
    H.X.drop_db(P)


def item_fast(name, r, P, R, S, broken, pending):
    out = {"progress_broken": broken}
    base_schema = H.pg_dump(P)
    H.create_role_db(R, template=P)
    H.create_role_db(S, template=P)
    out["seeded_rows"] = H.X.seed(S, random.Random(f"{H.SEED}:{name}:{r['path']}"))
    with H.X.connect(S) as c:
        c.execute("SET session_replication_role = replica")
        c.execute("DELETE FROM schema_migrations WHERE version LIKE 'zq%' OR version !~ '^[0-9]+$'")
        c.execute("DELETE FROM ar_internal_metadata WHERE key LIKE 'zq%' OR value LIKE 'zq%'")
    pg = M.Pg(f"postgresql://postgres@127.0.0.1:{H.PORT}/{S}", H.PSQL)
    pg.run(["-c", "ANALYZE"])
    stats = pg.json(M.STATS)
    with H.X.connect(S) as cc:
        cat = H.X.catalog(cc)
    pre = H.X.snapshot(S)
    res = boot(name, P, R, S, r["node"], r["path"], pending)
    post = H.X.snapshot(S)
    recs = res.get("render") or []
    rend = recs[0] if recs else {"path": r["path"], "sql": "", "transaction": True, "python_ops": [],
                                 "error": res.get("render_crash") or "no output"}
    rend["python_ops"] = FW.rails_ruby_ops(H.read_source(name, r["path"]))
    out["render"] = {k: rend.get(k) for k in ("sql", "transaction", "python_ops", "error", "name")}
    sql_stmts = M.split_sql(rend.get("sql") or "")
    named = [t["name"] for t in cat["tables"].values()
             if re.search(r"(?<![\w$])\"?" + re.escape(t["name"]) + r"\"?(?![\w$])", "\n".join(sql_stmts), re.I)]
    L = H.X.loss_label(H.strip_bookkeeping(pre), H.strip_bookkeeping(post))
    lab = res["label"]
    out["label"] = {"lost": L["lost"], "fails": bool(lab["error"])}
    out["run_error"] = lab["error"]
    out["lost_detail"] = L["lost_detail"][:10]
    prog = res["progress"]
    if prog["error"]:
        out["progress_error"] = f"{prog['failed']}: {prog['error'][:200]}"
    for d in (R, S):
        H.X.drop_db(d)
    out["product"] = H.product_side(name, rend, base_schema, bool(broken), stats)
    with open(os.path.join(HERE, "data", "inputs", f"{name}.jsonl"), "a") as f:   # to rebuild states without replay
        f.write(json.dumps({"path": r["path"], "base_schema": base_schema, "stats": stats}) + "\n")
    ex = []
    if broken:
        ex.append("progress_broken")
    if any(out["seeded_rows"].get(t, 0) == 0 for t in named if t in out["seeded_rows"]):
        ex.append("named_table_not_seeded")
    if any(t in named for t in L["untracked_tables"]):
        ex.append("untracked_rows")
    out["excluded"] = ex
    return out


H.build = build


def frame_ext(names):
    """Appends projects to the frame and the sample (the drawn sample of the first projects is left as it is): every
    eligible migration of stratum A, and the caps of B and C, with the seed "<SEED>:<project>:ext"."""
    H.ensure_infra()
    have = {json.loads(l)["project"] for l in open(os.path.join(HERE, "data", "frame.jsonl"))}
    for name in names:
        assert name not in have, name
        H.start_project(name)
        nodes = H.inner(name, "postgres", "plan")
        recs = []
        for i, n in enumerate(nodes):
            text = H.read_source(name, n["path"])
            recs.append({"project": name, "framework": "rails", "idx": i, "node": n["node"], "path": n["path"],
                         "sha256": __import__("hashlib").sha256(text.encode()).hexdigest(),
                         "stratum": H.stratum("rails", text),
                         "eligible": bool(n.get("down")) and not n.get("replaces") and not n["path"].startswith("/")})
        rng = random.Random(f"{H.SEED}:{name}:ext")
        pick = [r for r in recs if r["eligible"] and r["stratum"] == "A"]
        for st in "BC":
            pool = sorted([r for r in recs if r["eligible"] and r["stratum"] == st], key=lambda r: r["idx"])
            pick += rng.sample(pool, min(H.CAPS[st], len(pool)))
        with open(os.path.join(HERE, "data", "frame.jsonl"), "a") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")
        with open(os.path.join(HERE, "data", "sample.jsonl"), "a") as f:
            for r in sorted(pick, key=lambda r: r["idx"]):
                f.write(json.dumps(r) + "\n")
        by = {st: sum(1 for r in pick if r["stratum"] == st) for st in "ABC"}
        print(f"{name}: {len(recs)} migrations, eligible {sum(r['eligible'] for r in recs)}, sampled {len(pick)} {by}",
              flush=True)


# ---------------------------------------------------------------- the product side at 0.1.20+ (code probes)
from ekbasis.probes import probe_facts      # noqa: E402

PROBES = True                               # A1: the product commit runs the code probes before asking the model


def product_side(name, rec, base_schema, base_incomplete, stats):
    """As harness.product_side, mirroring check_bundle and _check_file at the product commit, now with the code probes
    (probes.probe_facts): their facts join the state, and a failure they reproduce is decided in code ("probe_fails")."""
    fw = H.PROJECTS[name]["framework"]
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
    with M.Scratch(H.ADMIN, H.PSQL) as sc:
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
        catalog = sc.db.json(M.CATALOG) or {}
        facts = [f"Run on this schema with no rows, the migration fails: {e}."] if e else []
        decided = None
        if PROBES and not e:
            pfacts, decided = probe_facts(sc, catalog, stmts, stats, tx, M.outside_bodies)
            facts += pfacts
            out["probe_facts"] = pfacts
        out["schema_error"] = e
        out["state"], out["shown"] = M.build_state(catalog, stmts, stats, fw, tx, facts, notes=[])
        if decided:
            out.update(decided="probe_fails", probe_decided=decided)
            return out
        if len(out["state"]) > M.MAX_CHARS:
            out["decided"] = "cannot_foresee_long"
    return out


H.product_side = product_side


def restate(names):
    """A1: the product side again, from the saved inputs (base schema and statistics per item), without replaying the
    histories. Labels, renders and exclusions are kept; only "product" is recomputed."""
    for name in names:
        items = [json.loads(l) for l in open(os.path.join(HERE, "data", "items", f"{name}.jsonl"))]
        inputs = {r["path"]: r for r in map(json.loads, open(os.path.join(HERE, "data", "inputs", f"{name}.jsonl")))}
        H.ensure_infra()
        out = []
        for r in items:
            if "harness_error" in r.get("excluded", []):
                out.append(r)
                continue
            i = inputs[r["path"]]
            r["product"] = product_side(name, r["render"], i["base_schema"], bool(r.get("progress_broken")), i["stats"])
            out.append(r)
        with open(os.path.join(HERE, "data", "items", f"{name}.jsonl"), "w") as f:
            for r in out:
                f.write(json.dumps(r, default=str) + "\n")
        print(name, len(out), flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "start":
        H.ensure_infra()
        for n in sys.argv[2:] or list(H.PROJECTS):
            try:
                H.start_project(n)
                print(n, "ready", flush=True)
            except Exception as ex:  # noqa: BLE001
                print(n, "FAILED", str(ex)[-1500:], flush=True)
    elif cmd == "frame":
        H.frame(sys.argv[2:] or None)
    elif cmd == "restate":
        if sys.argv[2] == "--no-probes":
            PROBES = False
            restate(sys.argv[3:])
        else:
            restate(sys.argv[2:])
    elif cmd == "frame_ext":
        frame_ext(sys.argv[2:])
    elif cmd == "build":
        for n in sys.argv[2:] or list(H.PROJECTS):
            H.build(n)
