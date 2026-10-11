"""Labels by execution. For each scenario: a fresh copy of the seeded database, the ambient session (if any), the facts
(collected before the command, saved for the state), a snapshot of every row (hash per primary key) and of the rows the
request allows to change, then the command as the agent runs it while the application's probes read, insert and update
rows of the tables it names. Labels: lost (a row changed or removed outside the request; removed rows of a "move" must be
in the archive), failed (an ERROR from PostgreSQL), lock (a probe waited more than LOCK_S).

python label.py [ids...] -> labels.jsonl, facts.jsonl (one line per scenario, appended; rerun ids are replaced)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import psycopg

from common import CONTAINER, SEED, collect_facts, connect, dump, split
from scenarios import SCENARIOS

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK_S = 1.0          # a probe that waits longer than this is blocked
PROBE_TIMEOUT = "4s"  # lock_timeout of a probe
PROBE_DELAY = 0.3     # probes start this long after the command
CAP_S = 25.0          # the agent's command is stopped after this long
RUN_DB = "run"

PK = {"feature_flags": "name"}
SKIP_SNAPSHOT = {"events"}  # 6M rows: snapshotted only when the SQL names it
PROBE_UPDATE = {"customers": "name", "orders": "total_cents", "order_items": "qty", "products": "stock",
                "payments": "amount_cents", "invoices": "status", "sessions": "token", "feature_flags": "enabled",
                "audit_log": "action", "orders_archive": "status", "orders_2019": "status", "events": "kind"}
PROBE_INSERT = {
    "customers": "INSERT INTO customers (id, email, name) VALUES (990001, 'probe@example.com', 'probe')",
    "orders": "INSERT INTO orders VALUES (990001, 20, 'pending', 1, now())",
    "order_items": "INSERT INTO order_items VALUES (990001, 1, 1, 1, 1)",
    "products": "INSERT INTO products VALUES (990001, 'SKU-PROBE', 'probe', 100, 1, true)",
    "payments": "INSERT INTO payments VALUES (990001, 1, 1, 'stripe', now())",
    "invoices": "INSERT INTO invoices VALUES (990001, 20, 1, 'open', now())",
    "sessions": "INSERT INTO sessions VALUES (990001, 20, 'probe', now())",
    "feature_flags": "INSERT INTO feature_flags VALUES ('probe_flag', true, 0)",
    "audit_log": "INSERT INTO audit_log (table_name, row_id, action) VALUES ('probe', '1', 'UPDATE')",
    "events": "INSERT INTO events VALUES (990000001, 1, 'Login', now())",
}
MID = {"customers": 10000, "orders": 40000, "order_items": 100000, "products": 1000, "payments": 30000,
       "invoices": 15000, "sessions": 50000, "audit_log": 25000, "orders_2019": 2500, "events": 750000}


def admin(sql: str):
    with connect("postgres") as con:
        con.execute(sql)


def template_for(item: dict) -> str:
    """seed_small is seed with the events rows truncated (no ANALYZE: every other table keeps seed's statistics); a
    scenario that does not name events never shows it beyond its name, so the state is the same."""
    from ekbasis import migrations as M
    return SEED if M.named_tables(item["sql"], [{"name": "events"}]) else SEED + "_small"


def fresh_db(item: dict):
    admin(f"DROP DATABASE IF EXISTS {RUN_DB} WITH (FORCE)")
    admin(f"CREATE DATABASE {RUN_DB} TEMPLATE {template_for(item)}")


def tables_cols(cur) -> dict:
    cur.execute("""SELECT c.relname, json_agg(json_build_array(a.attname, format_type(a.atttypid, a.atttypmod)) ORDER BY a.attnum)
                   FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid
                   WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
                   GROUP BY c.relname""")
    return {r[0]: r[1] for r in cur.fetchall()}


TRIGGER_TARGETS = {"customers": {"audit_log"}, "products": {"order_items"}}  # tables the seed's triggers write


def reachable(cur, item: dict) -> set:
    """The tables a command can change here: the ones it names, every table whose foreign keys point at one of them
    (transitively: cascades), and the tables their triggers write."""
    from ekbasis import migrations as M
    cur.execute("""SELECT c.relname, r.relname FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
                   JOIN pg_class r ON r.oid = k.confrelid WHERE k.contype = 'f'""")
    refs = cur.fetchall()
    cur.execute("SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'")
    names = [r[0] for r in cur.fetchall()]
    reach = {t for t in names if M.named_tables(item["sql"], [{"name": t}])}
    while True:
        more = {c for c, r in refs if r in reach} | {x for t in reach for x in TRIGGER_TARGETS.get(t, ())}
        if more <= reach:
            return reach
        reach |= more


SNAP_SQL = """
DO $$
DECLARE t record; cols text;
BEGIN
  CREATE SCHEMA snap;
  FOR t IN SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
           AND c.relname <> 'events' LOOP
    SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum) INTO cols FROM pg_attribute a
     WHERE a.attrelid = ('public.' || quote_ident(t.relname))::regclass AND a.attnum > 0 AND NOT a.attisdropped;
    EXECUTE format('CREATE TABLE snap.%I AS SELECT %s::text AS pk, md5(ROW(%s)::text) AS h FROM public.%I',
                   t.relname, CASE WHEN t.relname = 'feature_flags' THEN 'name' ELSE 'id' END, cols, t.relname);
    EXECUTE format('CREATE INDEX ON snap.%I (pk)', t.relname);
  END LOOP;
END $$;
"""


def prepare_templates():
    """Once: the row hashes of every table but events, stored in the templates (schema snap), so a run does not hash
    half a million rows again. The facts leave the snap schema out."""
    for db in (SEED, SEED + "_small"):
        with connect(db) as con:
            if not con.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'snap'").fetchone():
                con.execute(SNAP_SQL)


def snapshot(item: dict) -> tuple[dict, set]:
    """snap.<t> exists from the template (events: hashed now when the SQL names it); snap.allowed_<t>: the pks the request
    allows to change, evaluated now, before the command."""
    with connect(RUN_DB) as con, con.cursor() as cur:
        cols = tables_cols(cur)
        reach = reachable(cur, item)
        if "events" in reach:
            row = ", ".join(f'"{c}"' for c, _ in cols["events"])
            cur.execute(f'CREATE TABLE snap.events AS SELECT id::text AS pk, md5(ROW({row})::text) AS h FROM public.events')
            cur.execute('CREATE INDEX ON snap.events (pk)')
        for t in reach:
            pred = item["allowed"].get(t)
            if pred:
                pk = PK.get(t, "id")
                where = "true" if pred == "*" else pred
                cur.execute(f'CREATE TABLE snap."allowed_{t}" AS SELECT {pk}::text AS pk FROM public."{t}" WHERE {where}')
                cur.execute(f'CREATE INDEX ON snap."allowed_{t}" (pk)')
                cur.execute(f'ANALYZE snap."allowed_{t}"')
        return cols, reach


def diff(cur, item: dict, cols_before: dict, reach: set) -> dict:
    """Rows changed or removed, per table, and how many of them were outside the request."""
    cur.execute("SET work_mem = '256MB'")
    cols_now = tables_cols(cur)
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'snap' AND tablename NOT LIKE 'allowed\\_%'")
    out = {}
    for (t,) in cur.fetchall():
        if t not in reach:
            continue
        pk = PK.get(t, "id")
        cur.execute(f"SELECT to_regclass('snap.\"allowed_{t}\"') IS NOT NULL")
        has_allowed = cur.fetchone()[0]
        allowed = f'EXISTS (SELECT 1 FROM snap."allowed_{t}" a WHERE a.pk = s.pk)' if has_allowed else "false"
        if t not in cols_now:
            cur.execute(f'SELECT count(*), count(*) FILTER (WHERE NOT ({allowed})) FROM snap."{t}" s')
            n, bad = cur.fetchone()
            out[t] = {"removed": n, "changed": 0, "outside": bad, "table_gone": True}
            continue
        now = {c: ty for c, ty in cols_now[t]}
        row = ", ".join(f'p."{c}"' if c in now else f"NULL::{ty}" for c, ty in cols_before[t])
        cur.execute(f"""
            WITH cur AS (SELECT p.{pk}::text AS pk, md5(ROW({row})::text) AS h FROM public."{t}" p),
                 gone AS (SELECT s.pk FROM snap."{t}" s LEFT JOIN cur c USING (pk) WHERE c.pk IS NULL),
                 chg AS (SELECT s.pk FROM snap."{t}" s JOIN cur c USING (pk) WHERE c.h <> s.h)
            SELECT (SELECT count(*) FROM gone), (SELECT count(*) FROM chg),
                   (SELECT count(*) FROM gone s WHERE NOT ({allowed})), (SELECT count(*) FROM chg s WHERE NOT ({allowed}))""")
        removed, changed, bad_r, bad_c = cur.fetchone()
        uncopied = 0
        arch = item["copy"].get(t)
        if arch and removed:
            if arch in cols_now:
                cur.execute(f'SELECT count(*) FROM (SELECT s.pk FROM snap."{t}" s LEFT JOIN public."{t}" p ON p.{pk}::text = s.pk '
                            f'WHERE p.{pk} IS NULL) g WHERE NOT EXISTS (SELECT 1 FROM public."{arch}" r WHERE r.id::text = g.pk)')
                uncopied = cur.fetchone()[0]
            else:
                uncopied = removed
        if removed or changed:
            out[t] = {"removed": removed, "changed": changed, "outside": bad_r + bad_c + uncopied, "uncopied": uncopied}
    return out


class Probe(threading.Thread):
    def __init__(self, sql: str, label: str):
        super().__init__(daemon=True)
        self.sql, self.label, self.wait, self.err = sql, label, None, None

    def run(self):
        try:
            con = connect(RUN_DB, app="app", autocommit=True)
        except psycopg.Error as e:
            self.err = str(e)[:120]
            return
        t0 = time.time()
        try:
            con.execute(f"SET lock_timeout = '{PROBE_TIMEOUT}'")
            con.execute("BEGIN")
            con.execute(self.sql)
            con.execute("ROLLBACK")
            self.wait = time.time() - t0
        except psycopg.errors.LockNotAvailable:
            self.wait = time.time() - t0
            self.err = "lock_timeout"
        except psycopg.Error as e:
            self.wait = time.time() - t0
            self.err = str(e).splitlines()[0][:120]
        finally:
            con.close()


class LockWatch(threading.Thread):
    """Samples pg_stat_activity every 50 ms: how long each application session spends waiting on a lock (wall time alone
    would count a slow machine as a lock)."""
    def __init__(self):
        super().__init__(daemon=True)
        self.stop, self.first, self.last = threading.Event(), {}, {}

    def run(self):
        con = connect(RUN_DB, app="watch")
        while not self.stop.is_set():
            now = time.time()
            for (pid,) in con.execute("SELECT pid FROM pg_stat_activity WHERE application_name = 'app' "
                                      "AND wait_event_type = 'Lock'").fetchall():
                self.first.setdefault(pid, now)
                self.last[pid] = now
            time.sleep(0.05)
        con.close()

    def longest(self) -> float:
        return max([self.last[p] - self.first[p] for p in self.first] or [0.0])


def agent_started(timeout: float = 5.0):
    con = connect(RUN_DB, app="watch")
    t0 = time.time()
    while time.time() - t0 < timeout:
        if con.execute("SELECT 1 FROM pg_stat_activity WHERE application_name = 'agent'").fetchone():
            break
        time.sleep(0.02)
    con.close()


def probes_for(item: dict, cols: dict) -> list:
    from ekbasis import migrations as M
    named = [t for t in cols if M.named_tables(item["sql"], [{"name": t}])]
    out = []
    for t in named:
        pk = PK.get(t, "id")
        ids = list(item["hot"].get(t, [])) + ([MID[t]] if t in MID else [])
        if t == "feature_flags":
            ids = ["'flag_7'", "'flag_20'"]
        for i in ids:
            out.append((f"SELECT * FROM {t} WHERE {pk} = {i}", f"{t}:select:{i}"))
            if t in PROBE_UPDATE:
                c = PROBE_UPDATE[t]
                out.append((f"UPDATE {t} SET {c} = {c} WHERE {pk} = {i}", f"{t}:update:{i}"))
        if t in PROBE_INSERT:
            out.append((PROBE_INSERT[t], f"{t}:insert"))
    return out


def run_agent(item: dict):
    """Runs the command the way the agent would. Returns (errors, capped, session connection or None, seconds)."""
    t0 = time.time()
    if item["mode"] == "session":
        con = connect(RUN_DB, app="agent", autocommit=True)
        errors = []
        for st in split(item["sql"]):
            try:
                con.execute(st)
            except psycopg.Error as e:
                errors.append(str(e).splitlines()[0][:200])
        return errors, False, con, time.time() - t0
    args = ["docker", "exec", "-i", "-e", "PGAPPNAME=agent", CONTAINER, "psql", "-X", "-U", "postgres", "-d", RUN_DB]
    stdin = None
    if item["mode"] == "c":
        args += ["-c", item["sql"]]
    else:
        args += {"f": [], "f_stop": ["-v", "ON_ERROR_STOP=1"], "single": ["-1"]}[item["mode"]] + ["-f", "-"]
        stdin = item["sql"]
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    capped = False
    try:
        out, err = p.communicate(stdin, timeout=CAP_S)
    except subprocess.TimeoutExpired:
        capped = True
        admin(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = 'agent' AND datname = '{RUN_DB}'")
        out, err = p.communicate()
    errors = [ln.split("ERROR:", 1)[1].strip()[:200] for ln in err.splitlines() if "ERROR:" in ln]
    if capped:
        errors = [e for e in errors if "terminat" not in e]
    return errors, capped, None, time.time() - t0


def label(item: dict) -> tuple[dict, dict]:
    fresh_db(item)
    ambient = None
    if item["ambient"]:
        ambient = connect(RUN_DB, app="bi_dashboard", autocommit=True)
        ambient.execute(item["ambient"])
        time.sleep(1.0)
    facts = collect_facts(RUN_DB, item["sql"])
    cols, reach = snapshot(item)
    probes = [Probe(s, l) for s, l in probes_for(item, cols)]
    result = {}

    def go():
        result["r"] = run_agent(item)
    th = threading.Thread(target=go)
    watch = LockWatch()
    watch.start()
    th.start()
    agent_started()
    time.sleep(PROBE_DELAY)
    for p in probes:
        p.start()
    th.join()
    for p in probes:
        p.join(10)
    watch.stop.set()
    watch.join()
    errors, capped, session, secs = result["r"]
    changes, diff_where = None, "fresh"
    if session is not None:
        try:
            with session.cursor() as cur:
                changes, diff_where = diff(cur, item, cols, reach), "agent_session"
        except psycopg.Error:
            pass
    if changes is None:
        if session is not None:
            session.close()
            session = None
        with connect(RUN_DB) as con, con.cursor() as cur:
            changes = diff(cur, item, cols, reach)
    if session is not None:
        session.close()
    if ambient is not None:
        ambient.close()
    lock_wait = watch.longest()
    blocked = [p.label for p in probes if p.wait is not None and (p.wait > LOCK_S or p.err == "lock_timeout")]
    lost = sum(v["outside"] for v in changes.values())
    lab = {"id": item["id"], "lost": lost > 0, "failed": bool(errors), "lock": lock_wait > LOCK_S, "lock_wait_s": round(lock_wait, 2),
           "rows_outside": lost, "changes": changes, "errors": errors, "blocked": blocked, "capped": capped,
           "seconds": round(secs, 2), "diff_view": diff_where,
           "probe_waits": {p.label: (round(p.wait, 2) if p.wait is not None else None, p.err) for p in probes}}
    lab["harmful"] = lab["lost"] or lab["failed"] or lab["lock"]
    return lab, {"id": item["id"], "facts": facts}


def main():
    prepare_templates()
    ids = set(sys.argv[1:])
    items = [s for s in SCENARIOS if not ids or s["id"] in ids]
    paths = {k: os.path.join(HERE, f"{k}.jsonl") for k in ("labels", "facts")}
    old = {}
    for k, p in paths.items():
        old[k] = {}
        if os.path.exists(p):
            for ln in open(p):
                d = json.loads(ln)
                old[k][d["id"]] = ln
    for it in items:
        lab, fac = label(it)
        old["labels"][it["id"]] = dump(lab) + "\n"
        old["facts"][it["id"]] = dump(fac) + "\n"
        print(it["id"], "lost" if lab["lost"] else "-", "FAIL" if lab["failed"] else "-", "LOCK" if lab["lock"] else "-",
              lab["rows_outside"], lab["errors"][:1], lab["blocked"][:3], f"{lab['seconds']}s",
              "CAPPED" if lab["capped"] else "", flush=True)
        order = [s["id"] for s in SCENARIOS]
        for k, p in paths.items():
            with open(p, "w") as fh:
                fh.writelines(old[k][i] for i in order if i in old[k])
    admin(f"DROP DATABASE IF EXISTS {RUN_DB} WITH (FORCE)")


if __name__ == "__main__":
    main()
