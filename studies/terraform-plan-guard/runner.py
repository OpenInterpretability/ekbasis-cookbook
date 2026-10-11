"""Executes each scenario and labels it from what actually happened (no model involved):
apply v1 -> seed data -> plan v2 (saved: plan.json + live facts) -> apply the saved plan while probing the endpoints
-> search for the seeded data, compare exposure probes before/after -> clean up.

Labels: lost (the seeded data is found nowhere afterwards: not in a running container, a remaining volume, a host
directory, a database of the scenario, or the file), down (a probe that succeeded before fails at some moment during
the apply or in the 3 s after), exposed (an exposure probe that failed before succeeds after, or a port is newly
published on all interfaces), failed (tofu apply exits non-zero).

usage: runner.py [ids...]   (results in runs/s<id>/result.json)
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import psycopg2

import facts as F
import scenarios as SC

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(ROOT, "runs")
ENV = dict(os.environ, TF_PLUGIN_CACHE_DIR=os.path.join(ROOT, "plugin-cache"), TF_IN_AUTOMATION="1",
           TF_INPUT="0", CHECKPOINT_DISABLE="1")
ADMIN = dict(host="127.0.0.1", port=SC.PG_ADMIN_PORT, user="postgres", password="tfgpass", connect_timeout=2)
WIDE = ("", "0.0.0.0", "::")


def sh(args, cwd=None, timeout=300, env=None):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    return r.returncode, r.stdout + r.stderr


def tofu(d, *args, timeout=600):
    return sh(["tofu", *args, "-no-color"], cwd=d, timeout=timeout, env=ENV)


def admin(sql, db="postgres", fetch=False):
    conn = psycopg2.connect(dbname=db, **ADMIN)
    conn.autocommit = True
    try:
        with conn.cursor() as c:
            c.execute(sql)
            return c.fetchall() if fetch else None
    finally:
        conn.close()


def subst(text, d):
    return text.replace("@DIR@", d).replace("@BIND@", os.path.join(d, "bind"))


# ---------------------------------------------------------------- seeding

def wait_pg_container(name, t=60):
    end = time.time() + t
    while time.time() < end:
        rc, _ = sh(["docker", "exec", name, "psql", "-U", "postgres", "-c", "select 1"], timeout=10)
        if rc == 0:
            return True
        time.sleep(1)
    return False


def seed(op, tok, d):
    if op["op"] == "pg_container":
        c = op["container"]
        if not wait_pg_container(c):
            raise RuntimeError(f"postgres in {c} never came up")
        time.sleep(2)   # the image restarts the server once after init
        if not wait_pg_container(c):
            raise RuntimeError(f"postgres in {c} never came up")
        sql = (f"create table app_t (id serial primary key, v text); "
               f"insert into app_t (v) select '{tok}' from generate_series(1, 1000); checkpoint;")
        rc, out = sh(["docker", "exec", c, "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-c", sql])
        if rc:
            raise RuntimeError(out)
        rc, out = sh(["docker", "exec", c, "sh", "-c",
                      f'echo {tok} > "${{PGDATA:-/var/lib/postgresql/data}}/tfg_marker"'])
        if rc:
            raise RuntimeError(out)
    elif op["op"] == "pg_db":
        db, sch = op["db"], op["schema"]
        conn = psycopg2.connect(dbname=db, **ADMIN)
        conn.autocommit = True
        with conn.cursor() as c:
            if op["hstore"]:
                c.execute(f"create table {sch}.app_t (id serial primary key, v text, h hstore)")
                c.execute(f"insert into {sch}.app_t (v, h) select '{tok}', hstore('k', '{tok}') "
                          f"from generate_series(1, 1000)")
            else:
                c.execute(f"create table {sch}.app_t (id serial primary key, v text)")
                c.execute(f"insert into {sch}.app_t (v) select '{tok}' from generate_series(1, 1000)")
            c.execute(f"alter table {sch}.app_t owner to {op['owner']}")
        conn.close()
    elif op["op"] == "redis":
        c = op["container"]
        for _ in range(30):
            rc, out = sh(["docker", "exec", c, "redis-cli", "PING"], timeout=10)
            if "PONG" in out:
                break
            time.sleep(1)
        rc, out = sh(["docker", "exec", c, "redis-cli", "SET", "tfgkey", tok])
        if "OK" not in out:
            raise RuntimeError(out)
    elif op["op"] == "append_file":
        with open(subst(op["path"], d), "a") as f:
            for k in range(50):
                f.write(f"entry {k} {tok}\n")
    else:
        raise ValueError(op)


# ---------------------------------------------------------------- probes

def probe_once(p):
    try:
        if p["kind"] == "http":
            with urllib.request.urlopen(f"http://127.0.0.1:{p['port']}/", timeout=1) as r:
                return r.status == 200
        if p["kind"] == "tcp":
            with socket.create_connection(("127.0.0.1", p["port"]), timeout=1):
                return True
        if p["kind"] == "redis":
            with socket.create_connection(("127.0.0.1", p["port"]), timeout=1) as s:
                s.settimeout(1)
                s.sendall(b"PING\r\n")
                return s.recv(16).startswith(b"+PONG")
        if p["kind"] == "pg":
            conn = psycopg2.connect(host="127.0.0.1", port=p["port"], dbname=p["db"], user=p["user"],
                                    password=p["password"], connect_timeout=1)
            try:
                with conn.cursor() as c:
                    c.execute(p["sql"])
                    c.fetchall()
                return True
            finally:
                conn.close()
    except Exception:
        return False
    raise ValueError(p)


class Prober(threading.Thread):
    def __init__(self, probes):
        super().__init__(daemon=True)
        self.probes, self.stop, self.fail, self.n = probes, threading.Event(), [0] * len(probes), 0

    def run(self):
        while not self.stop.is_set():
            for k, p in enumerate(self.probes):
                if not probe_once(p):
                    self.fail[k] += 1
            self.n += 1
            time.sleep(0.2)


def access(p):
    """True if the access works (exposure probes)."""
    try:
        if p["kind"] == "pg_noauth":
            conn = psycopg2.connect(host="127.0.0.1", port=p["port"], dbname="postgres", user="postgres",
                                    password="", connect_timeout=2)
            conn.close()
            return True
        if p["kind"] == "outsider":
            conn = psycopg2.connect(host="127.0.0.1", port=SC.PG_ADMIN_PORT, dbname=p["db"], user="tfg_outsider",
                                    password="outsider", connect_timeout=2)
            try:
                with conn.cursor() as c:
                    c.execute(p["sql"])
                    c.fetchall()
                return True
            finally:
                conn.close()
    except Exception:
        return False
    raise ValueError(p)


def wide_bindings(i):
    rc, out = sh(["docker", "ps", "-q", "--filter", f"name=^tfg-s{i}-"])
    ids = out.split()
    found = set()
    if not ids:
        return found
    for c in json.loads(sh(["docker", "inspect", *ids])[1]):
        for k, binds in ((c.get("NetworkSettings") or {}).get("Ports") or {}).items():
            for b in binds or []:
                if b.get("HostIp") in WIDE:
                    found.add(f"{b['HostPort']}->{k}")
    return found


# ---------------------------------------------------------------- data search

def find_data(s, tok, d, t_start):
    """Where the seeded data still is (a list of places); empty = lost."""
    i, where = s["id"], []
    for st in s["stores"]:
        if st["kind"] == "marker":
            rc, out = sh(["docker", "ps", "-q", "--filter", f"name=^tfg-s{i}-"])
            for cid in out.split():
                rc, o = sh(["docker", "exec", cid, "sh", "-c", 'cat "${PGDATA:-/var/lib/postgresql/data}/tfg_marker"'])
                if tok in o:
                    where.append(f"container {cid[:12]}")
            for v in volumes_to_search(i, t_start):
                rc, o = sh(["docker", "run", "--rm", "-v", f"{v}:/v:ro", "alpine:3.20", "sh", "-c",
                            "find /v -maxdepth 3 -name tfg_marker -exec cat {} +"], timeout=60)
                if tok in o:
                    where.append(f"volume {v[:24]}")
        elif st["kind"] == "redis":
            rc, out = sh(["docker", "ps", "-q", "--filter", f"name=^tfg-s{i}-"])
            for cid in out.split():
                for _ in range(10):
                    rc, o = sh(["docker", "exec", cid, "redis-cli", "GET", "tfgkey"])
                    if "LOADING" not in o:
                        break
                    time.sleep(1)
                if tok in o:
                    where.append(f"redis {cid[:12]}")
            for v in volumes_to_search(i, t_start):
                rc, o = sh(["docker", "run", "--rm", "-v", f"{v}:/v:ro", "alpine:3.20", "sh", "-c",
                            f"grep -rl {tok} /v"], timeout=60)
                if rc == 0 and o.strip():
                    where.append(f"volume {v[:24]}")
            bd = os.path.join(d, "bind")
            if os.path.isdir(bd):
                for f in os.listdir(bd):
                    if tok.encode() in open(os.path.join(bd, f), "rb").read():
                        where.append(f"bind {f}")
        elif st["kind"] == "pg_db":
            dbs = [r[0] for r in admin(f"select datname from pg_database where datname like 's{i}\\_%'", fetch=True)]
            for db in dbs:
                try:
                    rows = admin("select table_schema, table_name from information_schema.columns "
                                 f"where column_name = '{st['col']}' and table_name = 'app_t'", db=db, fetch=True)
                    for sch, t in rows:
                        expr = "h -> 'k'" if st["col"] == "h" else "v"
                        n = admin(f"select count(*) from {sch}.{t} where {expr} = '{tok}'", db=db, fetch=True)[0][0]
                        if n:
                            where.append(f"db {db}.{sch}.{t} ({n} rows)")
                except psycopg2.Error as e:
                    where.append(f"db {db}: unreadable ({str(e).strip()[:80]})")
        elif st["kind"] == "file":
            p = subst(st["path"], d)
            if os.path.exists(p) and tok in open(p).read():
                where.append(p)
    return where


def volumes_to_search(i, t_start):
    out = []
    rc, o = sh(["docker", "volume", "ls", "-q"])
    names = o.split()
    if not names:
        return out
    info = json.loads(sh(["docker", "volume", "inspect", *names])[1])
    for v in info:
        if v["Name"].startswith(f"tfg-s{i}-"):
            out.append(v["Name"])
        elif len(v["Name"]) == 64 and v.get("CreatedAt", "") >= t_start:
            out.append(v["Name"])   # anonymous volumes created during this scenario
    return out


# ---------------------------------------------------------------- cleanup

def cleanup(i, d):
    if os.path.exists(os.path.join(d, "terraform.tfstate")):
        tofu(d, "destroy", "-auto-approve", "-input=false", "-lock=false", timeout=300)
    rc, out = sh(["docker", "ps", "-aq", "--filter", f"name=^tfg-s{i}-"])
    if out.split():
        sh(["docker", "rm", "-fv", *out.split()])
    rc, out = sh(["docker", "volume", "ls", "-q", "--filter", f"name=^tfg-s{i}-"])
    if out.split():
        sh(["docker", "volume", "rm", "-f", *out.split()])
    rc, out = sh(["docker", "network", "ls", "-q", "--filter", f"name=^tfg-s{i}-"])
    if out.split():
        sh(["docker", "network", "rm", *out.split()])
    for (db,) in admin(f"select datname from pg_database where datname like 's{i}\\_%'", fetch=True):
        admin(f'drop database "{db}" with (force)')
    for (r,) in admin(f"select rolname from pg_roles where rolname like 's{i}\\_%'", fetch=True):
        admin(f'drop role "{r}"')


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def run(s):
    i = s["id"]
    d = os.path.join(RUNS, f"s{i}")
    if os.path.isdir(d):
        cleanup(i, d)
        shutil.rmtree(d)
    os.makedirs(os.path.join(d, "bind"))
    tok = f"tok{i}x{secrets.token_hex(4)}"
    res = {"id": i, "title": s["title"], "family": s["family"], "token": tok}
    log = []
    holder = None
    try:
        t_start = utc_now()
        open(os.path.join(d, "main.tf"), "w").write(SC.HEADER + subst(s["v1"], d))
        rc, out = tofu(d, "init", "-input=false")
        if rc:
            raise RuntimeError("init: " + out[-1500:])
        rc, out = tofu(d, "apply", "-auto-approve", "-input=false")
        log.append(out[-3000:])
        if rc:
            raise RuntimeError("apply v1: " + out[-1500:])
        for op in s["seed"]:
            seed(op, tok, d)
        if s["hold"]:
            h = s["hold"]
            holder = psycopg2.connect(host="127.0.0.1", port=SC.PG_ADMIN_PORT, dbname=h["db"], user=h["user"],
                                      password=h["password"], connect_timeout=3)
        before_acc = [access(p) for p in s["access"]]
        before_wide = wide_bindings(i)
        res["data_before"] = find_data(s, tok, d, t_start) if s["stores"] else []
        if s["stores"] and not res["data_before"]:
            raise RuntimeError("seeded data not found before the change")
        open(os.path.join(d, "main.tf"), "w").write(SC.HEADER + subst(s["v2"], d))
        rc, out = tofu(d, "plan", "-out=plan.bin", "-input=false")
        res["plan_text"] = out[-6000:]
        if rc:
            res["plan_error"] = out[-2000:]
            return res
        rc, pj = sh(["tofu", "show", "-json", "plan.bin"], cwd=d, env=ENV)
        open(os.path.join(d, "plan.json"), "w").write(pj)
        plan = json.loads(pj)
        fx = F.collect(plan)
        json.dump(fx, open(os.path.join(d, "facts.json"), "w"), indent=1)
        base = [all(probe_once(p) for _ in range(3)) for p in s["probes"]]
        res["probe_baseline_ok"] = base
        live = [p for p, ok in zip(s["probes"], base) if ok]
        pr = Prober(live)
        pr.start()
        t0 = time.time()
        rc, out = tofu(d, "apply", "-input=false", "plan.bin")
        res["apply_s"] = round(time.time() - t0, 1)
        time.sleep(3)
        pr.stop.set()
        pr.join()
        res["apply_rc"] = rc
        res["apply_out"] = out[-4000:]
        res["probe_fail"] = pr.fail
        res["probe_rounds"] = pr.n
        if holder:
            try:
                holder.close()
            except Exception:
                pass
            holder = None
        time.sleep(1)
        res["data_after"] = find_data(s, tok, d, t_start) if s["stores"] else []
        after_acc = [access(p) for p in s["access"]]
        after_wide = wide_bindings(i)
        res["access_before"], res["access_after"] = before_acc, after_acc
        res["wide_before"], res["wide_after"] = sorted(before_wide), sorted(after_wide)
        res["labels"] = {
            "lost": bool(s["stores"]) and not res["data_after"],
            "down": any(f > 0 for f in pr.fail),
            "exposed": any(a and not b for a, b in zip(after_acc, before_acc)) or bool(after_wide - before_wide),
            "failed": rc != 0,
        }
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"[:3000]
    finally:
        if holder:
            try:
                holder.close()
            except Exception:
                pass
        res["log"] = log
        json.dump(res, open(os.path.join(d, "result.json"), "w"), indent=1)
        try:
            cleanup(i, d)
        except Exception as e:
            res["cleanup_error"] = str(e)
            json.dump(res, open(os.path.join(d, "result.json"), "w"), indent=1)
    return res


def ensure_outsider():
    if not admin("select 1 from pg_roles where rolname = 'tfg_outsider'", fetch=True):
        admin("create role tfg_outsider login password 'outsider'")


if __name__ == "__main__":
    ensure_outsider()
    ids = [int(x) for x in sys.argv[1:]] or [s["id"] for s in SC.S]
    for i in ids:
        t = time.time()
        r = run(SC.BY_ID[i])
        print(f"s{i:<3} {time.time() - t:5.0f}s {r.get('labels') or r.get('error') or r.get('plan_error', '')[:300]}  "
              f"| {r['title']}", flush=True)
