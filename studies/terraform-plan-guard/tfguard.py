"""Terraform plan guard (pilot, not shipped): state from FACTS (the plan JSON + live facts read before the apply),
typed questions to Ekbasis, verdict and reason decided in code. Also the frozen rule baseline.

    state, notes = build_state(plan, facts)
    answers = client.ask(state, QUESTIONS)
    verdict = decide(answers)
"""
from __future__ import annotations

import json
import re

from ekbasis import prompts as P

RULES = ("An OpenTofu (Terraform) plan is about to be applied to live infrastructure on one server: Docker containers "
         "and volumes, and a PostgreSQL server whose databases are used by running applications. Applying the plan "
         "carries out the resource changes below in dependency order. Replacing a resource destroys the old one and "
         "then creates the new one, unless the plan says the new one is created first (create_before_destroy). If a "
         "change fails, the apply stops there; the changes already made stay made.")

# Notes: how the providers behave, one sentence each, added only when a change in the plan needs it.
NOTE_CONTAINER = ("Destroying a Docker container also deletes its anonymous volumes; a named volume or a host directory "
                  "mounted into it is kept unless that volume is destroyed too. A new container starts from its image: "
                  "files the old one wrote outside its named volumes and host directories are not in it.")
NOTE_VOLUME = "Docker refuses to delete a volume that a container (running or stopped) still uses, and the change fails."
NOTE_NAME = "Docker refuses to create a container whose name, or published host port, is already in use, and the change fails."
NOTE_PG_INIT = ("The postgres image applies POSTGRES_PASSWORD and POSTGRES_HOST_AUTH_METHOD only when it initializes an "
                "empty data directory; a data directory that already holds a database keeps its users and pg_hba.conf.")
NOTE_DB = ("Destroying a postgresql_database drops the database with everything stored in it; PostgreSQL refuses to drop "
           "or rename a database while other sessions are connected to it, and the change fails.")
NOTE_SCHEMA = ("A postgresql_schema is destroyed with its tables only when drop_cascade = true; otherwise destroying a "
               "schema that still holds tables fails. Renaming a schema keeps its tables under the new name.")
NOTE_EXT = ("Destroying a postgresql_extension with drop_cascade = true also drops the columns whose type comes from the "
            "extension; without it, the change fails while such columns exist.")
NOTE_ROLE = ("Clients log in with a role's name and password: after a role is renamed, gets a new password, or has "
             "login = false, new connections with the old name or password fail; sessions already open stay open.")
NOTE_ALLOW = "A database with allow_connections = false refuses every new connection."
NOTE_FILE = ("Creating a local_file writes the configured content to its path, replacing whatever the file holds; the plan "
             "creates it again when the file on disk no longer matches what OpenTofu wrote.")
NOTE_EXPOSE = ("A Docker port published with ip 0.0.0.0 (or with no ip) is reachable from every network the server is on; "
               "with ip 127.0.0.1 only from the server itself.")
NOTE_PUBLIC = "A privilege granted to PUBLIC applies to every role, including any role that can log in."

Q_LOST = P.yes_no(
    "Does applying this plan permanently lose any stored data: rows in a database table, or data that a service or an "
    "application wrote (a database data directory, the contents of a volume, lines an application added to a file), "
    "that exists before and afterwards is in no database, volume, directory or file at all? Data kept in a volume or "
    "host directory that is not destroyed is not lost, even if no container uses it any more. Content that OpenTofu "
    "itself writes from the configuration does not count. If a change fails, only what was done before it counts.")
Q_DOWN = P.yes_no(
    "Does a service that answers before the apply stop answering its current clients at some moment during the apply "
    "or right after it: the same published host port, the same database name, the same role name and password? A "
    "short gap while a container is replaced counts, and so does a refused connection, a failed login, or a database "
    "or table the clients use that is gone or renamed. A change that fails without touching the service does not.")
Q_EXPOSED = P.yes_no(
    "After this plan is applied, can someone who could not before reach a service or read data without credentials "
    "of their own: a port newly published on all network interfaces (0.0.0.0, or no ip given) instead of only "
    "127.0.0.1, a database server that now accepts connections without a password, or a table that every role "
    "(PUBLIC) can now read? Access granted to one specific role that logs in with its own password does not count, "
    "and access that is narrowed does not count.")
Q_FAILS = P.yes_no("Does applying this plan fail (some change ends with an error)?")
QUESTIONS = {"lost": Q_LOST, "down": Q_DOWN, "exposed": Q_EXPOSED, "fails": Q_FAILS}
THRESHOLD = 0.5

SECRET = re.compile(r"PASS|SECRET|TOKEN|KEY", re.I)


def redact(v):
    if isinstance(v, str) and "=" in v:
        k, _, val = v.partition("=")
        if SECRET.search(k):
            return f"{k}=(secret)"
    return v


def fmt(v):
    if v is True or v is False:
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, list):
        if v and all(isinstance(x, dict) for x in v):
            return "; ".join(fmt(x) for x in v)
        return "[" + ", ".join(fmt(redact(x)) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k} = {fmt(x)}" for k, x in v.items() if x not in (None, "", [], {})) + "}"
    if isinstance(v, str):
        return json.dumps(v)
    return str(v)


def kb(n):
    if n is None:
        return "size unknown"
    return f"{n / 1024:.0f} MB" if n >= 1024 else f"{n} KB"


# ---------------------------------------------------------------- current state

def pg_readers(acl):
    """Roles with SELECT in a PostgreSQL ACL string ('' = PUBLIC)."""
    out = []
    for item in re.findall(r'"?([^,{}"]*)"?', acl or ""):
        if "=" in item:
            who, _, rest = item.partition("=")
            privs = rest.split("/")[0]
            if "r" in privs:
                out.append(who or "PUBLIC")
    return out


def describe_container(addr, v, f):
    if not f or not f.get("exists"):
        return f"{addr}: container {v.get('name')} (not found on the server)"
    bits = [f"{addr}: container {f['name']}, image {f['image']}, {'running' if f['running'] else 'stopped'}"]
    for p in f["ports"]:
        ip = p["host_ip"] or "0.0.0.0"
        bits.append(f"publishes {ip}:{p['host_port']} -> {p['internal']} ({'answering' if p['answers'] else 'not answering'})")
    if not f["ports"]:
        bits.append("publishes no port")
    conf_env = {x.partition("=")[0] for x in (v.get("env") or [])}
    env = {k: x for k, x in f["env"].items() if k in conf_env or k == "PGDATA"}
    if env:
        bits.append("environment: " + ", ".join(f"{k}={x}" for k, x in sorted(env.items())))
    for m in f["mounts"]:
        if m["type"] == "bind":
            bits.append(f"host directory {m['source']} mounted at {m['dest']} ({kb(m['kb'])})")
        elif m["anonymous"]:
            bits.append(f"anonymous volume (created by Docker for the image's VOLUME {m['dest']}) at {m['dest']} "
                        f"({kb(m['kb'])})")
        else:
            bits.append(f"named volume {m['name']} mounted at {m['dest']} ({kb(m['kb'])})")
    for path, n in (f.get("unmounted_data_dirs") or {}).items():
        bits.append(f"data directory {path} is in the container's own filesystem, on no volume ({kb(n)})")
    if not f["mounts"]:
        bits.append("no volumes or host directories mounted")
    return "; ".join(bits)


def describe_db(db):
    if not db or not db.get("exists"):
        return f"database {db.get('name') if db else '?'} does not exist"
    bits = [f"database {db['name']} owned by {db['owner']}"]
    if not db["allow_connections"]:
        bits.append("allow_connections = false")
    if db["connection_limit"] not in (-1, None):
        bits.append(f"connection limit {db['connection_limit']}")
    s = db.get("sessions") or {}
    bits.append("open sessions: " + (", ".join(f"{n} as role {u}" for u, n in s.items()) if s else "none"))
    tabs = db.get("tables") or []
    if tabs:
        tl = []
        for t in tabs:
            r = pg_readers(t["acl"])
            extra = f", readable by {', '.join(r)}" if r else ""
            tl.append(f"{t['schema']}.{t['table']} ({t['rows']:,} rows, owner {t['owner']}{extra})")
        bits.append("tables: " + "; ".join(tl))
    else:
        bits.append("no tables (empty)")
    if db.get("acl"):
        bits.append(f"database privileges: {db['acl']}")
    for e in db.get("extensions") or []:
        cols = e["columns"]
        bits.append(f"extension {e['name']} installed" + (f"; columns of its types: {', '.join(cols)}" if cols
                                                          else "; no column uses its types"))
    return "; ".join(bits)


def resources(plan):
    out = {}

    def walk(m):
        for r in m.get("resources") or []:
            if r.get("mode") == "managed":
                out[r["address"]] = (r["type"], r.get("values") or {})
        for c in m.get("child_modules") or []:
            walk(c)

    walk(((plan.get("prior_state") or {}).get("values") or {}).get("root_module") or {})
    return out


def current_state(plan, facts):
    res = resources(plan)
    lines, dbs_done = [], set()
    if not res:
        return ["(nothing is managed yet)"]
    for addr, (typ, v) in res.items():
        if typ == "docker_container":
            lines.append(describe_container(addr, v, facts["containers"].get(addr)))
        elif typ == "docker_volume":
            f = facts["volumes"].get(addr) or {}
            used = ", ".join(f.get("used_by") or []) or "no container"
            lines.append(f"{addr}: volume {v.get('name')} ({kb(f.get('kb'))}), used by {used}")
        elif typ == "docker_network":
            lines.append(f"{addr}: network {v.get('name')}")
        elif typ == "postgresql_database":
            lines.append(f"{addr}: " + describe_db(facts["databases"].get(v.get("name"))))
            dbs_done.add(v.get("name"))
        elif typ == "postgresql_role":
            f = facts["roles"].get(addr) or {}
            s = f.get("sessions") or {}
            lines.append(f"{addr}: role {v.get('name')}, {'can log in' if v.get('login') else 'cannot log in'}"
                         f"{', has a password' if v.get('password') else ''}; open sessions: "
                         + (", ".join(f"{n} in database {d}" for d, n in s.items()) if s else "none"))
        elif typ == "postgresql_schema":
            lines.append(f"{addr}: schema {v.get('name')} in database {v.get('database')}, drop_cascade = "
                         f"{fmt(v.get('drop_cascade'))}")
        elif typ == "postgresql_extension":
            lines.append(f"{addr}: extension {v.get('name')} in database {v.get('database')}, drop_cascade = "
                         f"{fmt(v.get('drop_cascade'))}")
        elif typ == "postgresql_grant":
            lines.append(f"{addr}: grants {fmt(v.get('privileges'))} on {v.get('object_type')} "
                         f"{fmt(v.get('objects')) if v.get('objects') else '(all in schema)' if v.get('object_type') == 'table' else ''}"
                         f" in database {v.get('database')} to role {v.get('role')}")
        elif typ == "local_file":
            f = facts["files"].get(addr) or {}
            state_lines = (v.get("content") or "").count("\n")
            if not f.get("exists"):
                lines.append(f"{addr}: file {v.get('filename')} is missing on disk")
            elif f.get("same_as_state"):
                lines.append(f"{addr}: file {v.get('filename')} ({f['lines']} lines), same as the content OpenTofu wrote")
            else:
                lines.append(f"{addr}: file {v.get('filename')} now has {f['lines']} lines on disk; OpenTofu wrote "
                             f"{state_lines} line(s) — the file was changed after OpenTofu wrote it"
                             + (" (lines were added at the end)" if f.get("starts_with_state") else ""))
        else:
            lines.append(f"{addr}: {typ}")
    for name, db in (facts.get("databases") or {}).items():
        if name not in dbs_done:
            lines.append("PostgreSQL " + describe_db(db))
    return lines


# ---------------------------------------------------------------- the changes

REASONS = {
    "replace_because_cannot_update": "a changed attribute cannot be updated in place",
    "replace_because_tainted": "it is tainted",
    "replace_by_request": "replacement was requested",
    "replace_by_triggers": "a replace_triggered_by reference changed",
    "delete_because_no_resource_config": "it was removed from the configuration",
    "delete_because_no_module": "its module was removed",
    "delete_because_wrong_repetition": "its count/for_each changed",
    "delete_because_count_index": "its count index no longer exists",
    "delete_because_each_key": "its for_each key no longer exists",
    "read_because_config_unknown": "",
}
NOISE = {"id", "network_data", "container_logs", "exit_code", "bridge", "gateway", "ip_address", "ip_prefix_length",
         "content_md5", "content_sha1", "content_sha256", "content_sha512", "content_base64sha256",
         "content_base64sha512", "mountpoint"}


def changed_attrs(rc):
    ch = rc["change"]
    before, after = ch.get("before") or {}, ch.get("after") or {}
    unknown = ch.get("after_unknown") or {}
    forced = {p[0] for p in ch.get("replace_paths") or [] if p}
    out = []
    for k in sorted(set(before) | set(after) | set(unknown)):
        if k in NOISE:
            continue
        b, a, u = before.get(k), after.get(k), unknown.get(k)
        if u is True or (u and a in (None, [], {})):
            if k in forced or (k in after and a is None and k in ("name",)):
                out.append(f"{k}: {fmt(b)} -> (known after apply)")
            continue
        if b == a:
            continue
        if a in (None, [], {}, "") and b in (None, [], {}, "", 0, False) :
            continue
        if "delete" in ch["actions"] and "create" in ch["actions"] and a in (None, [], {}) and k not in forced:
            continue   # computed attributes reset by the replacement
        out.append(f"{k}: {fmt(b)} -> {fmt(a)}")
    return out, forced


def created_attrs(rc):
    a = rc["change"].get("after") or {}
    keys = {"docker_container": ("name", "image", "env", "ports", "volumes", "networks_advanced"),
            "docker_volume": ("name",), "docker_network": ("name",),
            "postgresql_database": ("name", "owner", "template"),
            "postgresql_role": ("name", "login"),
            "postgresql_schema": ("name", "database", "drop_cascade"),
            "postgresql_extension": ("name", "database"),
            "postgresql_grant": ("database", "role", "schema", "object_type", "objects", "privileges"),
            "local_file": ("filename", "content", "file_permission")}.get(rc["type"], ())
    return [f"{k} = {fmt(a.get(k))}" for k in keys if a.get(k) not in (None, [], {})]


def action_line(rc):
    ch = rc["change"]
    acts = ch["actions"]
    addr = rc["address"]
    why = REASONS.get(rc.get("action_reason") or "", "")
    if acts == ["create"]:
        attrs = created_attrs(rc)
        return f"Create {addr}" + (": " + "; ".join(attrs) if attrs else "")
    if acts == ["delete"]:
        return f"Destroy {addr}" + (f" ({why})" if why else "")
    if acts == ["forget"]:
        return f"Stop managing {addr}: it is removed from the OpenTofu state and left running as it is (not destroyed)"
    attrs, forced = changed_attrs(rc)
    ch_text = "; ".join(attrs[:10]) if attrs else "no attribute shown"
    if acts == ["update"]:
        return f"Update {addr} in place: {ch_text}"
    if acts in (["delete", "create"], ["create", "delete"]):
        order = ("destroy the old one, then create the new one" if acts[0] == "delete"
                 else "create the new one first, then destroy the old one (create_before_destroy)")
        f = f", forced by the change to {', '.join(sorted(forced))}" if forced else ""
        return f"Replace {addr} ({order}{f}): {ch_text}"
    return f"{'/'.join(acts)} {addr}: {ch_text}"


def changes(plan):
    return [rc for rc in plan.get("resource_changes") or [] if rc["mode"] == "managed"
            and rc["change"]["actions"] not in (["no-op"], ["read"])]


def notes_for(plan, facts):
    out = []
    rcs = changes(plan)
    types = {rc["type"] for rc in rcs}
    acts = {(rc["type"], a) for rc in rcs for a in rc["change"]["actions"]}

    def add(n):
        if n not in out:
            out.append(n)

    if ("docker_container", "delete") in acts:
        add(NOTE_CONTAINER)
    if ("docker_volume", "delete") in acts:
        add(NOTE_VOLUME)
    if ("docker_container", "create") in acts and ("docker_container", "delete") in acts:
        add(NOTE_NAME)
    for rc in rcs:
        a = rc["change"].get("after") or {}
        if rc["type"] == "docker_container" and any(re.match(r"POSTGRES_(PASSWORD|HOST_AUTH_METHOD)=", e or "")
                                                    for e in a.get("env") or []):
            add(NOTE_PG_INIT)
    if "postgresql_database" in types:
        add(NOTE_DB)
        if any(rc["type"] == "postgresql_database" and (rc["change"].get("after") or {}).get("allow_connections") is False
               for rc in rcs):
            add(NOTE_ALLOW)
    if "postgresql_schema" in types:
        add(NOTE_SCHEMA)
    if "postgresql_extension" in types:
        add(NOTE_EXT)
    if "postgresql_role" in types:
        add(NOTE_ROLE)
    if "local_file" in types:
        add(NOTE_FILE)
    if "docker_container" in types:
        add(NOTE_EXPOSE)
    if "postgresql_grant" in types:
        add(NOTE_PUBLIC)
    return out


def build_state(plan, facts):
    rcs = changes(plan)
    acts = [action_line(rc) for rc in rcs]
    moved = [f"{rc['previous_address']} is now {rc['address']} (moved; no change)" for rc in plan.get("resource_changes") or []
             if rc.get("previous_address") and rc["change"]["actions"] == ["no-op"]]
    if not acts:
        acts = ["Apply the plan: it changes no resource" + (" (" + "; ".join(moved) + ")" if moved else "")]
    elif moved:
        acts.append("Record the moves: " + "; ".join(moved))
    state = "\n".join(current_state(plan, facts))
    return P.world_state(RULES, state, acts, notes=notes_for(plan, facts), notes_label="How these providers behave")


# ---------------------------------------------------------------- the verdict, in code

def decide(p: dict, threshold: float = THRESHOLD) -> dict:
    """p: {"lost", "down", "exposed", "fails"} -> probabilities. Verdict and reason decided here, not by the model."""
    flags = [k for k in ("lost", "exposed", "down") if p.get(k, 0) >= threshold]
    words = {"lost": "may permanently lose stored data", "exposed": "may expose a service or data more widely",
             "down": "may interrupt a running service during the apply"}
    if not flags:
        reason = (f"no data loss, exposure or interruption foreseen (lose {p['lost']:.0%}, expose {p['exposed']:.0%}, "
                  f"interrupt {p['down']:.0%})")
    else:
        reason = "; ".join(f"{words[k]} ({p[k]:.0%})" for k in flags)
    if p.get("fails", 0) >= threshold:
        reason += f"; the apply may fail part-way ({p['fails']:.0%})"
    return {"risky": bool(flags), "flags": flags, "reason": reason}


# ---------------------------------------------------------------- rule baseline (frozen in the prereg)

STATEFUL = {"docker_volume", "postgresql_database", "postgresql_schema", "local_file"}
DATA_IMAGE = re.compile(r"postgres|mysql|mariadb|redis|mongo", re.I)
WIDE = ("", "0.0.0.0", "::", None)


def rule(plan) -> dict:
    """R_lost: any delete (or replace) of a stateful resource: docker_volume, postgresql_database, postgresql_schema,
    local_file, or a docker_container whose image is a database/cache image or that mounts any volume.
    R_down: any delete or destroy-before-create replace of a serving resource: a docker_container that publishes a
    port, a postgresql_database, a postgresql_role.
    R_exposed: a docker_container whose planned ports include one on all interfaces (ip 0.0.0.0/empty) for an internal
    port that was not already published on all interfaces; a container env newly containing
    POSTGRES_HOST_AUTH_METHOD=trust; a postgresql_grant to role public created or with privileges added."""
    out = {"lost": False, "down": False, "exposed": False}
    for rc in changes(plan):
        ch, typ = rc["change"], rc["type"]
        acts = ch["actions"]
        b, a = ch.get("before") or {}, ch.get("after") or {}
        deletes = "delete" in acts
        if deletes:
            if typ in STATEFUL:
                out["lost"] = True
            if typ == "docker_container" and (DATA_IMAGE.search(b.get("image") or "") or b.get("volumes")):
                out["lost"] = True
            serving = (typ == "docker_container" and b.get("ports")) or typ in ("postgresql_database", "postgresql_role")
            if serving and acts[0] == "delete":
                out["down"] = True
        if typ == "docker_container" and "create" in acts:
            wide_before = {p.get("internal") for p in b.get("ports") or [] if p.get("ip") in WIDE}
            if any(p.get("ip") in WIDE and p.get("internal") not in wide_before for p in a.get("ports") or []):
                out["exposed"] = True
            if "POSTGRES_HOST_AUTH_METHOD=trust" in (a.get("env") or []) and \
                    "POSTGRES_HOST_AUTH_METHOD=trust" not in (b.get("env") or []):
                out["exposed"] = True
        if typ == "postgresql_grant" and (a.get("role") or "").lower() == "public":
            if set(a.get("privileges") or []) - set(b.get("privileges") or []):
                out["exposed"] = True
    out["risky"] = any(out.values())
    return out
