"""Rails eval (v6, on-code warn): the frozen v4 harness (../fw_eval/harness.py) with Rails projects. Differences:
- plan/apply run in Ruby (`bin/rails runner /tmp/ekh_rails.rb`): versions in order, applied with the migration context;
- the product's Rails renderer RUNS the new migration (Rails has no offline mode), so it runs on a throwaway copy of the
  progress database, never on the progress database or the seeded copy;
- Ruby that is not schema DSL is detected as the product does (ekbasis.frameworks.rails_ruby_ops);
- Rails' bookkeeping tables (schema_migrations, ar_internal_metadata) are not seeded and not labelled.
Steps and outputs as in v4/v5 (frame, build).
Mastodon's migrations use Redis: the label and progress runs reach a Redis on the eval network; the product side does
not (as in migrate-gen, its generator reaches only the scratch PostgreSQL).
Loomio was tried and left out before sampling: its oldest migrations inherit ActiveRecord::Migration without a version,
so its history cannot be replayed from an empty database (it loads db/schema.rb instead)."""
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "fw_eval"))
import harness as H                       # noqa: E402
X, M, FW = H.X, H.M, H.FW

H.HERE = HERE
H.SEED = "20261011:v6"
H.BOOKKEEPING = H.BOOKKEEPING | {"schema_migrations", "ar_internal_metadata"}
RB_SETUP = ("set -e; apt-get update -qq >/dev/null; apt-get install -y -qq build-essential git libpq-dev libyaml-dev "
            "libicu-dev libidn-dev libvips42 >/dev/null 2>&1; ")
COMMON_ENV = {"RAILS_ENV": "development", "SECRET_KEY_BASE": "e" * 128, "DISABLE_SPRING": "1",
              "BOOTSNAP_CACHE_DIR": "/tmp/bootsnap"}
H.PROJECTS = {
    "mastodon": dict(framework="rails", repo="fw/mastodon", workdir=".", image="ruby:4.0",
                     setup=RB_SETUP + "apt-get install -y -qq libvips42 >/dev/null 2>&1; bundle config set --local without 'test' && bundle install --quiet",
                     env=dict(COMMON_ENV, OTP_SECRET="o" * 64, LOCAL_DOMAIN="example.test",
                              ACTIVE_RECORD_ENCRYPTION_DETERMINISTIC_KEY="d" * 32,
                              ACTIVE_RECORD_ENCRYPTION_KEY_DERIVATION_SALT="s" * 32,
                              ACTIVE_RECORD_ENCRYPTION_PRIMARY_KEY="p" * 32, REDIS_URL="redis://ekeval-redis:6379"),
                     exclude=r"^db/post_migrate/"),
    "maybe": dict(framework="rails", repo="fw/maybe", workdir=".", image="ruby:3.4.4",
                  setup=RB_SETUP + "bundle config set --local without 'test' && bundle install --quiet",
                  env=dict(COMMON_ENV, SELF_HOSTED="true")),
}
H.STRATA["rails"] = (
    re.compile(r"\b(remove_column|remove_columns|drop_table|change_column|rename_column|rename_table|execute|"
               r"update_all|delete_all|destroy_all|find_each|in_batches|remove_reference|remove_belongs_to|"
               r"remove_timestamps|change_column_default)\b"),
    re.compile(r"null:\s*false|change_column_null|add_index[^\n]*unique|add_foreign_key|add_check_constraint|"
               r"validate_foreign_key|add_unique_constraint"),
)


def inner(name, db, action, nodes=None, timeout=3600):
    if action == "plan":                      # an empty role-owned database: Rails connects at boot
        db = f"plan_{name}"
        H.create_role_db(db)
    e = H.env_for(name, db)
    e["EKH_ACTION"] = action
    if nodes is not None:
        e["EKH_NODES"] = json.dumps(nodes)
    eargs = [x for k, v in e.items() for x in ("-e", f"{k}={v}")]
    p = H.sh("docker", "exec", *eargs, "-w", H.wd(name), H.ctr(name), "bin/rails", "runner", "/tmp/ekh_rails.rb",
             check=False, timeout=timeout)
    lines = [l for l in p.stdout.decode(errors="replace").splitlines() if l.startswith(H.MARK)]
    if not lines:
        raise RuntimeError(f"inner {action} failed: {p.stderr.decode(errors='replace')[-1500:]}")
    return json.loads(lines[-1][len(H.MARK):])


H.inner = inner


def render(name, db, path):
    """The product's Rails renderer (frameworks.RAILS_SCRIPT), on a throwaway copy: it runs the migration."""
    R = f"render_{name}"
    H.create_role_db(R, template=db)
    try:
        e = H.env_for(name, R)
        if "REDIS_URL" in e:          # the product's generator reaches only the scratch PostgreSQL: no Redis
            e["REDIS_URL"] = "redis://127.0.0.1:6379"
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
        rec["python_ops"] = FW.rails_ruby_ops(H.read_source(name, path))       # as frameworks.generate does
        return rec
    finally:
        X.drop_db(R)


H.render = render
_start = H.start_project


def start_project(name):
    _start(name)
    c = H.ctr(name)
    H.sh("docker", "exec", "-i", c, "sh", "-c", "cat > /tmp/ekh_rails.rb",
         input_bytes=open(os.path.join(HERE, "ekh_rails.rb"), "rb").read())
    H.sh("docker", "exec", "-i", c, "sh", "-c", "cat > /tmp/ekbasis_rails.rb", input_bytes=FW.RAILS_SCRIPT.encode())


H.start_project = start_project


def item(name, r, P, broken):
    """As harness.item, with Rails' bookkeeping tables cleaned after seeding."""
    out = {"progress_broken": broken}
    base_schema = H.pg_dump(P)
    rend = render(name, P, r["path"])
    out["render"] = {k: rend.get(k) for k in ("sql", "transaction", "python_ops", "error", "name")}
    S = f"seed_{name}"
    H.create_role_db(S, template=P)
    out["seeded_rows"] = X.seed(S, random.Random(f"{H.SEED}:{name}:{r['path']}"))
    with X.connect(S) as c:
        c.execute("SET session_replication_role = replica")
        c.execute("DELETE FROM schema_migrations WHERE version LIKE 'zq%' OR version !~ '^[0-9]+$'")
        c.execute("DELETE FROM ar_internal_metadata WHERE key LIKE 'zq%' OR value LIKE 'zq%'")
    pg = M.Pg(f"postgresql://postgres@127.0.0.1:{H.PORT}/{S}", H.PSQL)
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
    L = X.loss_label(H.strip_bookkeeping(pre), H.strip_bookkeeping(post))
    out["label"] = {"lost": L["lost"], "fails": bool(res["error"])}
    out["run_error"] = res["error"]
    out["lost_detail"] = L["lost_detail"][:10]
    X.drop_db(S)
    out["product"] = H.product_side(name, rend, base_schema, bool(broken), stats)
    ex = []
    if broken:
        ex.append("progress_broken")
    if any(out["seeded_rows"].get(t, 0) == 0 for t in named if t in out["seeded_rows"]):
        ex.append("named_table_not_seeded")
    if any(t in named for t in L["untracked_tables"]):
        ex.append("untracked_rows")
    out["excluded"] = ex
    return out


H.item = item

if __name__ == "__main__":
    if sys.argv[1] == "start":
        H.ensure_infra()
        for n in sys.argv[2:] or list(H.PROJECTS):
            try:
                H.start_project(n)
                print(n, "ready", flush=True)
            except Exception as ex:  # noqa: BLE001
                print(n, "FAILED", str(ex)[-1200:], flush=True)
    elif sys.argv[1] == "frame":
        H.frame(sys.argv[2:] or None)
    elif sys.argv[1] == "build":
        for n in sys.argv[2:] or list(H.PROJECTS):
            H.build(n)
