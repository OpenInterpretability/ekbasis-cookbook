"""Live facts a plan guard can read safely before the apply (read-only): Docker inspect, volume sizes, whether published
ports answer, and the PostgreSQL catalog (tables, exact row counts, ACLs, sessions, extension dependencies). Collected
raw; tfguard.py renders them. Which objects to inspect comes only from the plan JSON (prior state and changes)."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess

import psycopg2

PG = dict(host="127.0.0.1", port=47432, user="postgres", password="tfgpass", connect_timeout=3)


def sh(*args, timeout=30):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def resources(plan):
    """Every resource in the prior state (including child modules) as {address: (type, values)}."""
    out = {}

    def walk(m):
        for r in m.get("resources") or []:
            if r.get("mode") == "managed":
                out[r["address"]] = (r["type"], r.get("values") or {})
        for c in m.get("child_modules") or []:
            walk(c)

    walk(((plan.get("prior_state") or {}).get("values") or {}).get("root_module") or {})
    return out


def tcp_answers(port, host="127.0.0.1"):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def docker_json(*args):
    rc, out, _ = sh("docker", *args)
    if rc:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def du_volume(name):
    rc, out, _ = sh("docker", "run", "--rm", "-v", f"{name}:/v:ro", "alpine:3.20", "du", "-sk", "/v", timeout=60)
    return int(out.split()[0]) if rc == 0 and out.strip() else None


def du_in_container(name, path):
    rc, out, _ = sh("docker", "exec", name, "du", "-sk", path, timeout=30)
    return int(out.split()[0]) if rc == 0 and out.strip() else None


def container_facts(name):
    c = docker_json("inspect", "--size", name)
    if not c:
        return {"name": name, "exists": False}
    c = c[0]
    img = docker_json("image", "inspect", c["Config"]["Image"]) or [{}]
    declared = sorted(((img[0].get("Config") or {}).get("Volumes") or {}).keys())
    env = {}
    for e in c["Config"].get("Env") or []:
        k, _, v = e.partition("=")
        env[k] = "(secret)" if re.search(r"PASS|SECRET|TOKEN|KEY", k) else v
    mounts = []
    for m in c.get("Mounts") or []:
        anon = m["Type"] == "volume" and re.fullmatch(r"[0-9a-f]{64}", m.get("Name") or "") is not None
        kb = du_in_container(name, m["Destination"]) if c["State"]["Running"] else None
        mounts.append({"type": m["Type"], "name": m.get("Name"), "source": m.get("Source") if m["Type"] == "bind" else None,
                       "dest": m["Destination"], "anonymous": anon, "kb": kb})
    pgdata = env.get("PGDATA")
    data_dirs = {}
    if pgdata and c["State"]["Running"] and not any(m["dest"] == pgdata or pgdata.startswith(m["dest"] + "/")
                                                    for m in mounts):
        data_dirs[pgdata] = du_in_container(name, pgdata)
    ports = []
    for k, binds in ((c.get("NetworkSettings") or {}).get("Ports") or {}).items():
        for b in binds or []:
            ports.append({"internal": k, "host_ip": b.get("HostIp"), "host_port": int(b["HostPort"]),
                          "answers": tcp_answers(int(b["HostPort"]))})
    return {"name": name, "exists": True, "running": c["State"]["Running"], "image": c["Config"]["Image"],
            "declared_volumes": declared, "env": env, "mounts": mounts, "unmounted_data_dirs": data_dirs,
            "ports": ports, "size_rw_kb": (c.get("SizeRw") or 0) // 1024,
            "restart": (c.get("HostConfig") or {}).get("RestartPolicy", {}).get("Name")}


def volume_facts(name):
    v = docker_json("volume", "inspect", name)
    if not v:
        return {"name": name, "exists": False}
    users = []
    rc, out, _ = sh("docker", "ps", "-a", "--filter", f"volume={name}", "--format", "{{.Names}}")
    users = [x for x in out.split() if x]
    return {"name": name, "exists": True, "kb": du_volume(name), "used_by": users}


def pg_query(db, sql, args=None):
    conn = psycopg2.connect(dbname=db, **PG)
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()
    finally:
        conn.close()


def db_facts(db):
    try:
        row = pg_query("postgres", "select pg_get_userbyid(datdba), datallowconn, datconnlimit, datacl::text "
                                   "from pg_database where datname = %s", (db,))
    except psycopg2.Error as e:
        return {"name": db, "error": str(e).strip()}
    if not row:
        return {"name": db, "exists": False}
    owner, allow, limit, acl = row[0]
    out = {"name": db, "exists": True, "owner": owner, "allow_connections": allow, "connection_limit": limit,
           "acl": acl, "tables": [], "extensions": [], "sessions": {}}
    sess = pg_query("postgres", "select usename, count(*) from pg_stat_activity where datname = %s "
                                "and pid <> pg_backend_pid() group by usename", (db,))
    out["sessions"] = {u: n for u, n in sess}
    if not allow:
        return out
    tabs = pg_query(db, "select n.nspname, c.relname, pg_get_userbyid(c.relowner), c.relacl::text from pg_class c "
                        "join pg_namespace n on n.oid = c.relnamespace where c.relkind = 'r' "
                        "and n.nspname not in ('pg_catalog', 'information_schema') order by 1, 2")
    for sch, t, owner_t, acl_t in tabs:
        n = pg_query(db, f'select count(*) from "{sch}"."{t}"')[0][0]
        out["tables"].append({"schema": sch, "table": t, "owner": owner_t, "rows": n, "acl": acl_t})
    out["schemas"] = [{"name": s, "owner": o} for s, o in pg_query(
        db, "select nspname, pg_get_userbyid(nspowner) from pg_namespace where nspname not like 'pg\\_%' "
            "and nspname <> 'information_schema'")]
    for (ext,) in pg_query(db, "select extname from pg_extension where extname <> 'plpgsql'"):
        cols = pg_query(db, """select n.nspname || '.' || c.relname || '.' || a.attname from pg_attribute a
            join pg_class c on c.oid = a.attrelid join pg_namespace n on n.oid = c.relnamespace
            join pg_depend d on d.objid = a.atttypid and d.deptype = 'e'
            join pg_extension e on e.oid = d.refobjid
            where e.extname = %s and a.attnum > 0 and not a.attisdropped and c.relkind = 'r'""", (ext,))
        out["extensions"].append({"name": ext, "columns": [c for (c,) in cols]})
    return out


def role_facts(role):
    try:
        r = pg_query("postgres", "select rolcanlogin, rolsuper from pg_roles where rolname = %s", (role,))
        if not r:
            return {"name": role, "exists": False}
        sess = pg_query("postgres", "select datname, count(*) from pg_stat_activity where usename = %s group by 1", (role,))
        owned = pg_query("postgres", "select count(*) from pg_database where pg_get_userbyid(datdba) = %s", (role,))[0][0]
        return {"name": role, "exists": True, "login": r[0][0], "sessions": {d: n for d, n in sess},
                "owns_databases": owned}
    except psycopg2.Error as e:
        return {"name": role, "error": str(e).strip()}


def file_facts(path, state_content):
    if not os.path.exists(path):
        return {"path": path, "exists": False}
    data = open(path, "rb").read()
    text = data.decode(errors="replace")
    return {"path": path, "exists": True, "bytes": len(data), "lines": text.count("\n"),
            "same_as_state": state_content is not None and text == state_content,
            "starts_with_state": state_content is not None and text.startswith(state_content)}


def collect(plan):
    """Facts about every object the plan's prior state names (the objects a change could affect)."""
    res = resources(plan)
    out = {"containers": {}, "volumes": {}, "databases": {}, "roles": {}, "files": {}}
    dbs = set()
    for addr, (typ, v) in res.items():
        if typ == "docker_container":
            out["containers"][addr] = container_facts(v.get("name"))
        elif typ == "docker_volume":
            out["volumes"][addr] = volume_facts(v.get("name"))
        elif typ == "postgresql_database":
            dbs.add(v.get("name"))
        elif typ in ("postgresql_schema", "postgresql_extension", "postgresql_grant"):
            dbs.add(v.get("database"))
        elif typ == "postgresql_role":
            out["roles"][addr] = role_facts(v.get("name"))
        elif typ == "local_file":
            out["files"][addr] = file_facts(v.get("filename"), v.get("content"))
    for db in sorted(d for d in dbs if d):
        out["databases"][db] = db_facts(db)
    return out
