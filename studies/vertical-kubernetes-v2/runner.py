"""Executes each scenario on the kind cluster vk8s2 and labels it from what actually happened (no model involved):
v1 -> wait ready -> seed a token -> read the live facts (facts.py) -> probe the client endpoints every 0.2 s ->
run the v2 commands -> watch until the rollout settles -> search for the token everywhere, re-run exposure probes.

Labels (v2 definitions; the differences from v1 are marked *)
  down     an endpoint whose baseline passed 3/3 has a gap of >= 2.0 s between two successful probes (with a failure
           inside it), or fails and never succeeds again for >= 2.0 s, from the change until the namespace settles
           (+5 s; window at least 20 s, at most 160 s*).
           * Repeated measurement: if the first run's longest gap is in [1.0, 4.0] s the scenario runs twice more; the
             measure is the MEDIAN of the three runs' longest gaps. down = median >= 2.0 s. A median in [1.5, 2.5) s is
             the declared GREY ZONE: down = null (excluded from the down label and, if nothing else is positive, from
             the composite).
  lost     the seeded token is found nowhere afterwards: not through the Service, not in any running pod of the
           namespace, not in any file under the node's local-path storage, emptyDir volumes or /mnt/vk (hostPath*).
  exposed  an access that failed before and succeeds after, keyed by channel and PORT* (not by Service name, so a
           renamed Service that is exactly as reachable as the old one is not new exposure):
             external:<port>       a Service nodePort (keyed by the Service port) or a hostPort, from a container
                                   outside the cluster;
             other-namespace:<port>  a ClusterIP Service port from a pod of another namespace; counted ONLY if the
                                   namespace had an ingress NetworkPolicy before the change* (otherwise every
                                   namespace could already reach every Service, and a new Service is not "let in");
             no-password:<probe>   the scenario's database or cache answering without credentials;
             rbac:<identity>:<verb>  the namespace default SA, the vk-outside default SA, or any authenticated user
                                   newly allowed to get/list secrets, create pods or create pods/exec in the namespace.
  failed   some v2 command exits non-zero (secondary).

usage: runner.py [ids...]   (results in runs/s<id>/)
"""
from __future__ import annotations

import fcntl
import json
import os
import secrets
import shlex
import statistics
import subprocess
import sys
import threading
import time

import facts as F
import kube as K
import scenarios as SC

RUNS = os.path.join(K.ROOT, "runs")
LOCKS = os.path.join(K.ROOT, ".locks")
GAP = 2.0
GREY = (1.5, 2.5)
REPEAT_BAND = (1.0, 4.0)
SETTLE_MAX = 150
WINDOW_MAX = 160
IDENTITIES = {"ns-default-sa": ["--as=system:serviceaccount:{ns}:default"],
              "other-ns-sa": ["--as=system:serviceaccount:vk-outside:default"],
              "any-user": ["--as=vk-random-user", "--as-group=system:authenticated"]}
VERBS = [("get", "secrets"), ("list", "secrets"), ("create", "pods"), ("create", "pods/exec")]


def sub(x, ns):
    return x.replace("@NS@", ns) if isinstance(x, str) else x


# ---------------------------------------------------------------- steps

def run_step(step, ns, d, tag, wait=False):
    """Returns (rc, command text, output)."""
    if "apply" in step:
        f = os.path.join(d, f"{tag}.json")
        open(f, "w").write(K.as_list([K.render(o, ns) for o in step["apply"]]))
        rc, out, err = K.k("apply", "-n", ns, "-f", f)
        return rc, f"kubectl apply -n {ns} -f {tag}.yaml", out + err
    if "delete" in step:
        outs, rc_all, texts = [], 0, []
        for kind, name in step["delete"]:
            name = sub(name, ns)
            rc, out, err = K.k("delete", "-n", ns, kind, name, "--wait=false")
            rc_all = rc_all or rc
            outs.append(out + err)
            texts.append(f"kubectl delete -n {ns} {kind} {name} --wait=false")
        return rc_all, " && ".join(texts), "".join(outs)
    if "helm" in step:
        h = step["helm"]
        f = os.path.join(d, f"{tag}-values.json")
        json.dump(h["values"], open(f, "w"))
        args = ["upgrade", "--install", h["release"], K.chart_path(h["chart"]), "-n", ns, "-f", f]
        if wait:
            args += ["--wait", "--timeout", "6m"]
        rc, out, err = K.helm(*args, timeout=420)
        name, _, ver = h["chart"].rpartition("-")
        return rc, f"helm upgrade {h['release']} {name} --version {ver} -n {ns} -f {tag}-values.yaml", out + err
    if "helm_uninstall" in step:
        rel = step["helm_uninstall"]
        rc, out, err = K.helm("uninstall", rel, "-n", ns)
        return rc, f"helm uninstall {rel} -n {ns}", out + err
    raise ValueError(step)


def workloads(ns):
    j = K.kj("get", "deploy,sts", "-n", ns) or {"items": []}
    return j["items"]


def settled(ns):
    for w in workloads(ns):
        sp, st, md = w["spec"], w.get("status") or {}, w["metadata"]
        want = sp.get("replicas", 1)
        if st.get("observedGeneration", 0) < md.get("generation", 0):
            return False
        if w["kind"] == "Deployment":
            if not (st.get("updatedReplicas", 0) == want and st.get("readyReplicas", 0) == want
                    and st.get("replicas", 0) == want):
                return False
        else:
            us = sp.get("updateStrategy") or {}
            part = (us.get("rollingUpdate") or {}).get("partition", 0)
            if st.get("readyReplicas", 0) != want or st.get("replicas", 0) != want:
                return False
            if us.get("type", "RollingUpdate") == "RollingUpdate" and not part and want and \
                    st.get("currentRevision") != st.get("updateRevision"):
                return False
    pods = K.kj("get", "pods", "-n", ns) or {"items": []}
    return not any(p["metadata"].get("deletionTimestamp") for p in pods["items"])


def wait_ready(ns, t=420):
    end = time.time() + t
    while time.time() < end:
        if settled(ns) and workloads(ns):
            return True
        time.sleep(2)
    return False


# ---------------------------------------------------------------- probes

def fqdn(p, ns):
    return f"{p['host']}.{ns}.svc.cluster.local"


def mysql_cli(p, h, sql, user=None, pw=True):
    auth = f"-p{shlex.quote(p['password'])}" if pw else "--skip-password"
    return (f"timeout 3 mysql --connect-timeout=2 -h {h} -P {p['port']} -u {user or p['user']} {auth} -N -e "
            f"{shlex.quote(sql)}")


def probe_cmd(p, ns, pre=False):
    """pre=True: before seeding, the table does not exist yet, so a database probe only runs select 1."""
    h = fqdn(p, ns)
    if p["type"] == "http":
        return f"curl -sf -m 1 -o /dev/null http://{h}:{p['port']}{p.get('path', '/')}"
    if p["type"] == "tcp":
        return f"nc -z -w 1 {h} {p['port']}"
    if p["type"] == "pg":
        return (f"PGPASSWORD={shlex.quote(p['password'])} PGCONNECT_TIMEOUT=1 timeout 2 psql -h {h} -p {p['port']} "
                f"-U {p['user']} -d {p['db']} -tAc '{'select 1' if pre else 'select 1 from app_t limit 1'}' >/dev/null 2>&1")
    if p["type"] == "redis":
        auth = f"AUTH {p['password']}\\r\\n" if p.get("password") else ""
        return (f"printf '{auth}PING\\r\\nQUIT\\r\\n' | timeout 2 nc {h} {p['port']} 2>/dev/null | grep -q PONG")
    if p["type"] == "mysql":
        return mysql_cli(p, h, "select 1" if pre else f"select 1 from {p['db']}.app_t limit 1") + " >/dev/null 2>&1"
    raise ValueError(p)


class Prober(threading.Thread):
    """One loop inside the prober pod; each line '<k> <0|1>' is stamped with the host clock on arrival."""

    def __init__(self, probes, ns):
        super().__init__(daemon=True)
        body = "; ".join(f"if {probe_cmd(p, ns)}; then echo '{n} 1'; else echo '{n} 0'; fi" for n, p in enumerate(probes))
        self.mark = f"vkloop_{ns}x"
        script = f"while true; do : {self.mark}; {body}; sleep 0.2; done"
        self.proc = subprocess.Popen(["kubectl", "exec", "-n", "vk-probe", "prober", "--", "sh", "-c", script],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=K.ENV, bufsize=1)
        self.events = [[] for _ in probes]

    def run(self):
        for line in self.proc.stdout:
            parts = line.split()
            if len(parts) == 2:
                self.events[int(parts[0])].append((time.time(), parts[1] == "1"))

    def stop(self):
        self.proc.kill()
        # the loop keeps running inside the pod after kubectl dies; kill it there
        K.pexec(f"pkill -f 'vkloop_[{self.mark[7]}]{self.mark[8:]}' || true")


def outage(events, t0, t1):
    """Longest gap between successes containing a failure, within [t0, t1]; plus failure count."""
    ev = [(t, ok) for t, ok in events if t >= t0 - 1 and t <= t1]
    last_ok, saw_fail, worst, fails = None, False, 0.0, 0
    for t, ok in ev:
        if ok:
            if saw_fail and last_ok is not None:
                worst = max(worst, t - last_ok)
            last_ok, saw_fail = t, False
        else:
            fails += 1
            saw_fail = True
            if last_ok is None:
                last_ok = t0
    if saw_fail and last_ok is not None:
        worst = max(worst, t1 - last_ok)
    return round(worst, 2), fails


def baseline(p, ns, pre=False):
    ok = 0
    for _ in range(60):
        rc, _, _ = K.pexec(probe_cmd(p, ns, pre), timeout=15)
        ok = ok + 1 if rc == 0 else 0
        if ok >= 3:
            return True
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------- seeding and searching data

def pods_of(ns, selector=None):
    args = ["get", "pods", "-n", ns] + (["-l", selector] if selector else [])
    j = K.kj(*args) or {"items": []}
    return [p for p in j["items"] if (p.get("status") or {}).get("phase") == "Running"
            and not p["metadata"].get("deletionTimestamp")]


def container_of(pod):
    return pod["spec"]["containers"][0]["name"]


def pexec_pod(pod, ns, cmd, timeout=60):
    return K.k("exec", "-n", ns, pod["metadata"]["name"], "-c", container_of(pod), "--", "sh", "-c", cmd,
               timeout=timeout)


def pg_local(pod, ns, op, sql):
    c = (f"PGPASSWORD={shlex.quote(op['password'])} psql -h 127.0.0.1 -U {op['user']} -d {op['db']} -v ON_ERROR_STOP=1 "
         f"-tAc {shlex.quote(sql)}")
    return pexec_pod(pod, ns, c)


def rd_local(pod, ns, op, *cmd):
    q = " ".join(shlex.quote(x) for x in cmd)
    if op.get("password"):
        c = f"redis-cli -a {shlex.quote(op['password'])} --no-auth-warning {q}"
    else:
        c = f"redis-cli {q}"
    return pexec_pod(pod, ns, c)


def my_local(pod, ns, op, sql):
    c = (f"M=$(command -v mariadb || command -v mysql); $M -h 127.0.0.1 -u {op['user']} "
         f"-p{shlex.quote(op['password'])} -N -e {shlex.quote(sql)}")
    return pexec_pod(pod, ns, c)


def gf_api(op, ns, method, path, body=None):
    h = f"{op['host']}.{ns}.svc.cluster.local"
    data = f"-H 'Content-Type: application/json' -d {shlex.quote(json.dumps(body))}" if body is not None else ""
    return K.pexec(f"curl -s -m 5 -u admin:{shlex.quote(op['password'])} -X {method} {data} http://{h}{path}")


def seed(op, ns, tok):
    if op["op"] == "grafana":
        for _ in range(30):
            rc, out, err = gf_api(op, ns, "POST", "/api/dashboards/db",
                                  {"dashboard": {"title": tok, "panels": []}, "overwrite": False})
            if rc == 0 and '"status":"success"' in out:
                return
            time.sleep(3)
        raise RuntimeError("seed grafana: " + (out + err)[-500:])
    pods = pods_of(ns, op["pod"])
    if not pods:
        raise RuntimeError(f"no running pod for {op['pod']}")
    pod = pods[0]
    if op["op"] == "pg":
        sql = (f"create table app_t (id serial primary key, v text); insert into app_t (v) select '{tok}' from "
               f"generate_series(1, 1000);")
        for _ in range(20):
            rc, out, err = pg_local(pod, ns, op, sql)
            if rc == 0:
                pg_local(pod, ns, op, "checkpoint")   # needs superuser; the bitnami app user is not (WAL has the rows)
                return
            time.sleep(3)
        raise RuntimeError("seed pg: " + err[-500:])
    if op["op"] == "redis":
        for _ in range(20):
            rc, out, err = rd_local(pod, ns, op, "SET", "vkkey", tok)
            if "OK" in out:
                return
            time.sleep(2)
        raise RuntimeError("seed redis: " + (out + err)[-500:])
    if op["op"] == "mysql":
        sql = (f"create database if not exists {op['db']}; create table {op['db']}.app_t (id int auto_increment primary "
               f"key, v varchar(64)); insert into {op['db']}.app_t (v) select '{tok}' from "
               f"(select 1 from information_schema.columns limit 1000) x;")
        for _ in range(30):
            rc, out, err = my_local(pod, ns, op, sql)
            if rc == 0:
                my_local(pod, ns, op, "flush tables")
                return
            time.sleep(3)
        raise RuntimeError("seed mysql: " + (out + err)[-500:])
    raise ValueError(op)


def find_token(s, ns, tok):
    where = []
    for op in s["seed"]:
        probe = next((p for p in s["probes"] if p["type"] == op["op"] or
                      (op["op"] == "grafana" and p["type"] == "http")), None)
        if op["op"] == "grafana":
            rc, out, _ = gf_api(op, ns, "GET", f"/api/search?query={tok}")
            if rc == 0 and tok in out:
                where.append(f"service {op['host']}")
            continue
        h = fqdn(probe, ns)
        if op["op"] == "pg":
            rc, out, _ = K.pexec(f"PGPASSWORD={shlex.quote(op['password'])} PGCONNECT_TIMEOUT=2 psql -h {h} -U {op['user']} "
                                 f"-d {op['db']} -tAc \"select count(*) from app_t where v = '{tok}'\"")
            if rc == 0 and out.strip() not in ("", "0"):
                where.append(f"service {probe['host']} ({out.strip()} rows)")
        elif op["op"] == "redis":
            auth = f"AUTH {op['password']}\\r\\n" if op.get("password") else ""
            rc, out, _ = K.pexec(f"printf '{auth}GET vkkey\\r\\nQUIT\\r\\n' | timeout 3 nc {h} {probe['port']}")
            if tok in out:
                where.append(f"service {probe['host']}")
        elif op["op"] == "mysql":
            rc, out, _ = K.pexec(mysql_cli(probe, h, f"select count(*) from {op['db']}.app_t where v = '{tok}'"))
            if rc == 0 and out.strip() not in ("", "0"):
                where.append(f"service {probe['host']} ({out.strip()} rows)")
        for pod in pods_of(ns):
            if op["op"] == "pg":
                rc, out, _ = pg_local(pod, ns, op, f"select count(*) from app_t where v = '{tok}'")
                ok = rc == 0 and out.strip() not in ("", "0")
            elif op["op"] == "redis":
                rc, out, _ = rd_local(pod, ns, op, "GET", "vkkey")
                ok = tok in out
            else:
                rc, out, _ = my_local(pod, ns, op, f"select count(*) from {op['db']}.app_t where v = '{tok}'")
                ok = rc == 0 and out.strip() not in ("", "0")
            if ok:
                where.append(f"pod {pod['metadata']['name']}")
    if s["seed"]:
        rc, out, _ = K.node_sh(f"grep -rlF {tok} /var/local-path-provisioner /var/lib/kubelet/pods /mnt/vk 2>/dev/null "
                               f"| head -5", timeout=180)
        where += [f"node {x}" for x in out.split()]
    return where


# ---------------------------------------------------------------- exposure probes

def isolated(ns):
    """Does the namespace have a NetworkPolicy that restricts ingress (policyTypes Ingress, or ingress rules)?"""
    nps = (K.kj("get", "networkpolicy", "-n", ns) or {"items": []})["items"]
    return any("Ingress" in (np["spec"].get("policyTypes") or ["Ingress"]) for np in nps)


def access(s, ns, ip):
    out = {}
    svcs = (K.kj("get", "svc", "-n", ns) or {"items": []})["items"]
    for sv in svcs:
        for p in sv["spec"].get("ports") or []:
            if p.get("nodePort"):
                rc, _, _ = K.sh(["docker", "exec", K.OUTSIDER, "nc", "-z", "-w", "2", ip, str(p["nodePort"])])
                out[f"external:{p['port']}"] = out.get(f"external:{p['port']}", False) or rc == 0
            if sv["spec"].get("clusterIP") not in (None, "None"):
                rc, _, _ = K.pexec(f"nc -z -w 2 {sv['spec']['clusterIP']} {p['port']}", ns="vk-outside")
                out[f"other-namespace:{p['port']}"] = out.get(f"other-namespace:{p['port']}", False) or rc == 0
    for pod in (K.kj("get", "pods", "-n", ns) or {"items": []})["items"]:
        for c in pod["spec"]["containers"]:
            for p in c.get("ports") or []:
                if p.get("hostPort"):
                    rc, _, _ = K.sh(["docker", "exec", K.OUTSIDER, "nc", "-z", "-w", "2", ip, str(p["hostPort"])])
                    out[f"external:hostPort{p['hostPort']}"] = out.get(f"external:hostPort{p['hostPort']}", False) or rc == 0
    for p in s["probes"]:
        h = fqdn(p, ns)
        if p["type"] == "pg":
            ok = False
            for user in ("app", "postgres"):
                rc, _, _ = K.pexec(f"PGCONNECT_TIMEOUT=2 psql -w -h {h} -U {user} -d postgres -tAc 'select 1'")
                ok = ok or rc == 0
            out[f"no-password:{p['host']}"] = ok
        elif p["type"] == "redis":
            rc, o, _ = K.pexec(f"printf 'PING\\r\\nQUIT\\r\\n' | timeout 3 nc {h} {p['port']}")
            out[f"no-password:{p['host']}"] = "+PONG" in o
        elif p["type"] == "mysql":
            rc, _, _ = K.pexec(mysql_cli(p, h, "select 1", user="root", pw=False))
            out[f"no-password:{p['host']}"] = rc == 0
    for who, flags in IDENTITIES.items():
        for verb, res in VERBS:
            rc, o, _ = K.k("auth", "can-i", verb, res, "-n", ns, *[f.format(ns=ns) for f in flags])
            out[f"rbac:{who}:{verb}:{res}"] = o.strip() == "yes"
    return out


# ---------------------------------------------------------------- cleanup

def cleanup(ns):
    rels = K.helm("list", "-n", ns, "-q")[1].split()
    for r in rels:
        K.helm("uninstall", r, "-n", ns, "--wait", "--timeout", "2m")
    K.k("delete", "namespace", ns, "--wait=true", "--timeout=240s", timeout=260)
    K.k("delete", "clusterrolebinding,clusterrole,persistentvolume", "-l", f"vk8s-scenario={ns}", "--wait=false")
    pvs = (K.kj("get", "pv") or {"items": []})["items"]
    for pv in pvs:
        ref = pv["spec"].get("claimRef") or {}
        if ref.get("namespace") == ns:
            path = ((pv["spec"].get("hostPath") or pv["spec"].get("local") or {}).get("path"))
            K.k("delete", "pv", pv["metadata"]["name"], "--wait=true", "--timeout=60s")
            if path and path.startswith("/var/local-path-provisioner/"):
                K.node_sh(f"rm -rf {shlex.quote(path)}")
    K.node_sh(f"rm -rf /mnt/vk/{ns}")


# ---------------------------------------------------------------- locks

class Locks:
    """Named file locks; GLOBAL is held shared by every scenario and exclusively by one that changes cluster-wide
    state, so such a scenario runs alone."""

    def __init__(self, names):
        os.makedirs(LOCKS, exist_ok=True)
        self.names = sorted(set(names) - {SC.GLOBAL})
        self.excl = SC.GLOBAL in names
        self.fds = []

    def __enter__(self):
        f = open(os.path.join(LOCKS, SC.GLOBAL), "a")
        fcntl.flock(f, fcntl.LOCK_EX if self.excl else fcntl.LOCK_SH)
        self.fds.append(f)
        for n in self.names:
            f = open(os.path.join(LOCKS, n), "a")
            fcntl.flock(f, fcntl.LOCK_EX)
            self.fds.append(f)
        return self

    def __exit__(self, *a):
        for f in reversed(self.fds):
            fcntl.flock(f, fcntl.LOCK_UN)
            f.close()


# ---------------------------------------------------------------- one scenario

def run(s, rep=0):
    i = s["id"]
    ns = f"s{i}"
    d = os.path.join(RUNS, ns if not rep else f"{ns}.rep{rep}")
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    cleanup(ns)
    tok = f"tok{i}x{secrets.token_hex(4)}"
    res = {"id": i, "split": s["split"], "origin": s["origin"], "title": s["title"], "token": tok, "rep": rep}
    pr = None
    try:
        K.k("create", "namespace", ns)
        K.k("label", "namespace", ns, "vk8s=scenario")
        for n, st in enumerate(s["v1"]):
            rc, cmd, out = run_step(st, ns, d, f"v1-{n}", wait=True)
            if rc:
                raise RuntimeError(f"v1 {cmd}: {out[-1500:]}")
        if not wait_ready(ns):
            raise RuntimeError("v1 never became ready")
        base0 = [baseline(p, ns, pre=True) for p in s["probes"]]
        if not all(base0):
            raise RuntimeError(f"probe baseline failed before seeding: {base0}")
        for op in s["seed"]:
            seed(op, ns, tok)
        ip = K.node_ip()
        res["data_before"] = find_token(s, ns, tok) if s["seed"] else []
        if s["seed"] and not res["data_before"]:
            raise RuntimeError("seeded data not found before the change")
        res["isolated_before"] = isolated(ns)
        res["access_before"] = access(s, ns, ip)
        if not rep:
            fx = F.collect(s, ns, d)
            json.dump(fx, open(os.path.join(d, "facts.json"), "w"), indent=1)
        base = [baseline(p, ns) for p in s["probes"]]
        res["probe_baseline_ok"] = base
        live = [p for p, ok in zip(s["probes"], base) if ok]
        if not live:
            raise RuntimeError("no probe passed its baseline")
        pr = Prober(live, ns)
        pr.start()
        time.sleep(2)
        t0 = time.time()
        cmds, rcs, outs = [], [], []
        for n, st in enumerate(s["v2"]):
            rc, cmd, out = run_step(st, ns, d, f"v2-{n}" if len(s["v2"]) > 1 else "change")
            cmds.append(cmd)
            rcs.append(rc)
            outs.append(out[-3000:])
            if rc:
                break
        res["commands"], res["rcs"], res["outputs"] = cmds, rcs, outs
        t_cmd = time.time()
        t_settle = None
        while time.time() - t0 < SETTLE_MAX:
            if time.time() - t0 >= 3 and settled(ns):
                t_settle = time.time()
                break
            time.sleep(1)
        t1 = min(max(t0 + 20, (t_settle or time.time()) + 5), t0 + WINDOW_MAX)
        while time.time() < t1:
            time.sleep(0.5)
        pr.stop()
        pr.join(timeout=5)
        events, pr = pr.events, None
        res["timing"] = {"commands_s": round(t_cmd - t0, 1), "settled_s": round(t_settle - t0, 1) if t_settle else None,
                         "window_s": round(t1 - t0, 1)}
        res["outage"] = []
        for p, ev in zip(live, events):
            gap, fails = outage(ev, t0, t1)
            res["outage"].append({"probe": p["name"], "max_gap_s": gap, "fails": fails, "n": len(ev),
                                  "fail_times": [round(t - t0, 2) for t, ok in ev if not ok][:200]})
        if not all(o["n"] > 20 for o in res["outage"]):
            raise RuntimeError(f"prober produced too few samples: {res['outage']}")
        # data: give the service up to 90 s to come back before searching
        end = time.time() + 90
        while time.time() < end and not all(K.pexec(probe_cmd(p, ns))[0] == 0 for p in live):
            time.sleep(2)
        res["data_after"] = find_token(s, ns, tok) if s["seed"] else []
        res["access_after"] = access(s, ns, ip)
        newly = sorted(k for k, v in res["access_after"].items() if v and not res["access_before"].get(k))
        res["newly_accessible_raw"] = newly
        res["newly_accessible"] = [k for k in newly
                                   if not (k.startswith("other-namespace:") and not res["isolated_before"])]
        res["max_gap_s"] = max(o["max_gap_s"] for o in res["outage"])
        res["labels"] = {"lost": bool(s["seed"]) and not res["data_after"],
                         "down": res["max_gap_s"] >= GAP,
                         "exposed": bool(res["newly_accessible"]),
                         "failed": any(rcs)}
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"[:3000]
    finally:
        if pr:
            pr.stop()
        json.dump(res, open(os.path.join(d, "result.json"), "w"), indent=1)
        if os.environ.get("VK_KEEP") != "1":
            try:
                cleanup(ns)
            except Exception as e:
                res["cleanup_error"] = str(e)
    return res


def label(s):
    """Run once; if the longest gap falls in [1.0, 4.0] s run twice more and take the MEDIAN gap (grey zone -> null)."""
    with Locks(s["locks"]):
        r = run(s)
        if r.get("labels") and REPEAT_BAND[0] <= r["max_gap_s"] <= REPEAT_BAND[1]:
            reps = [r]
            for k in (1, 2):
                x = run(s, rep=k)
                if x.get("labels"):
                    reps.append(x)
            gaps = [x["max_gap_s"] for x in reps]
            med = statistics.median(gaps)
            r["repeated"] = {"gaps": gaps, "median_gap_s": med,
                             "other_labels": [{k: v for k, v in x["labels"].items() if k != "down"} for x in reps]}
            r["labels"]["down"] = None if GREY[0] <= med < GREY[1] else med >= GAP
            json.dump(r, open(os.path.join(RUNS, f"s{s['id']}", "result.json"), "w"), indent=1)
    return r


if __name__ == "__main__":
    ids = [int(x) for x in sys.argv[1:]] or [s["id"] for s in SC.S]
    for i in ids:
        t = time.time()
        r = label(SC.BY_ID[i])
        if r["split"] == "test":   # test labels are not printed per item (they are read only by evaluate.py)
            print(f"s{i:<3} {time.time() - t:5.0f}s {'ERROR ' + r['error'][:300] if r.get('error') else 'labelled'}",
                  flush=True)
            continue
        print(f"s{i:<3} {time.time() - t:5.0f}s {r.get('labels') or r.get('error')} "
              f"{[(o['max_gap_s'], o['fails']) for o in r.get('outage', [])]} {r.get('newly_accessible', '')} "
              f"rc={r.get('rcs')} {('rep ' + str(r['repeated'])) if r.get('repeated') else ''}| {r['title']}",
              flush=True)
