"""Executes each scenario on the kind cluster and labels it from what actually happened (no model involved):
v1 -> wait ready -> seed a token -> read the live facts (facts.py) -> start probing the client endpoints every 0.2 s ->
run the v2 commands -> watch until the rollout settles -> search for the token everywhere, re-run exposure probes.

Labels
  down     an endpoint whose baseline passed 3/3 has a gap of >= 2.0 s between two successful probes (with at least one
           failure inside it), or fails and never succeeds again for >= 2.0 s, during the change and until the
           namespace settles (+5 s; window at least 20 s, at most 90 s after the change starts).
  lost     the seeded token is found nowhere afterwards: not through the Service, not in any running pod of the
           namespace, not in any directory of the node's local-path storage (Delete and Retain PVs) or emptyDir.
  exposed  an access that failed before and succeeds after: a Service or hostPort of the namespace reachable from a
           container outside the cluster (node IP), a Service reachable from a pod in another namespace (vk-outside),
           a database or cache answering without a password, or one of three identities (the namespace default
           ServiceAccount, the vk-outside default ServiceAccount, any authenticated user) newly allowed to
           get/list secrets, create pods or create pods/exec in the namespace.
  failed   some v2 command exits non-zero (secondary).

usage: runner.py [ids...]   (results in runs/s<id>/)
"""
from __future__ import annotations

import json
import os
import secrets
import shlex
import subprocess
import sys
import threading
import time

import facts as F
import kube as K
import scenarios as SC

RUNS = os.path.join(K.ROOT, "runs")
GAP = 2.0
IDENTITIES = {"ns-default-sa": ["--as=system:serviceaccount:{ns}:default"],
              "other-ns-sa": ["--as=system:serviceaccount:vk-outside:default"],
              "any-user": ["--as=vk-random-user", "--as-group=system:authenticated"]}
VERBS = [("get", "secrets"), ("list", "secrets"), ("create", "pods"), ("create", "pods/exec")]


# ---------------------------------------------------------------- steps

def run_step(step, ns, d, tag, wait=False):
    """Returns (rc, command text, output)."""
    if "apply" in step:
        f = os.path.join(d, f"{tag}.json")
        open(f, "w").write(K.as_list([K.render(o, ns) for o in step["apply"]]))
        cmd = ["kubectl", "apply", "-n", ns, "-f", f]
        rc, out, err = K.k(*cmd[1:])
        return rc, f"kubectl apply -n {ns} -f {tag}.yaml", out + err
    if "delete" in step:
        outs, rc_all, texts = [], 0, []
        for kind, name in step["delete"]:
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
            args += ["--wait", "--timeout", "5m"]
        rc, out, err = K.helm(*args)
        return rc, f"helm upgrade {h['release']} bitnami/{h['chart']} -n {ns} -f {tag}-values.yaml", out + err
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


def wait_ready(ns, t=300):
    end = time.time() + t
    while time.time() < end:
        if settled(ns) and workloads(ns):
            return True
        time.sleep(2)
    return False


# ---------------------------------------------------------------- probes

def fqdn(p, ns):
    return f"{p['host']}.{ns}.svc.cluster.local"


def probe_cmd(p, ns):
    h = fqdn(p, ns)
    if p["type"] == "http":
        return f"wget -q -T 1 -O /dev/null http://{h}:{p['port']}/"
    if p["type"] == "pg":
        return (f"PGPASSWORD={shlex.quote(p['password'])} PGCONNECT_TIMEOUT=1 timeout 2 psql -h {h} -p {p['port']} "
                f"-U {p['user']} -d {p['db']} -tAc 'select 1 from app_t limit 1' >/dev/null 2>&1")
    if p["type"] == "redis":
        return (f"printf 'AUTH {p['password']}\\r\\nPING\\r\\nQUIT\\r\\n' | timeout 2 nc {h} {p['port']} 2>/dev/null "
                f"| grep -q PONG")
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


def baseline(p, ns):
    ok = 0
    for _ in range(30):
        rc, _, _ = K.pexec(probe_cmd(p, ns), timeout=15)
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


def pg_local(pod, ns, op, sql):
    c = (f"PGPASSWORD={shlex.quote(op['password'])} psql -h 127.0.0.1 -U {op['user']} -d {op['db']} -v ON_ERROR_STOP=1 "
         f"-tAc {shlex.quote(sql)}")
    return K.k("exec", "-n", ns, pod["metadata"]["name"], "-c", container_of(pod), "--", "sh", "-c", c, timeout=60)


def rd_local(pod, ns, op, *cmd):
    q = " ".join(shlex.quote(x) for x in cmd)
    c = f"redis-cli -a {shlex.quote(op['password'])} --no-auth-warning {q} || redis-cli {q}"
    return K.k("exec", "-n", ns, pod["metadata"]["name"], "-c", container_of(pod), "--", "sh", "-c", c, timeout=60)


def seed(op, ns, tok):
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
    raise ValueError(op)


def find_token(s, ns, tok):
    where = []
    for op in s["seed"]:
        probe = next(p for p in s["probes"] if p["type"] == op["op"])
        h = fqdn(probe, ns)
        if op["op"] == "pg":
            rc, out, _ = K.pexec(f"PGPASSWORD={shlex.quote(op['password'])} PGCONNECT_TIMEOUT=2 psql -h {h} -U {op['user']} "
                                 f"-d {op['db']} -tAc \"select count(*) from app_t where v = '{tok}'\"")
            if rc == 0 and out.strip() not in ("", "0"):
                where.append(f"service {probe['host']} ({out.strip()} rows)")
        else:
            rc, out, _ = K.pexec(f"printf 'AUTH {op['password']}\\r\\nGET vkkey\\r\\nQUIT\\r\\n' | timeout 3 nc {h} "
                                 f"{probe['port']}")
            if tok in out:
                where.append(f"service {probe['host']}")
        for pod in pods_of(ns):
            if op["op"] == "pg":
                rc, out, _ = pg_local(pod, ns, op, f"select count(*) from app_t where v = '{tok}'")
                if rc == 0 and out.strip() not in ("", "0"):
                    where.append(f"pod {pod['metadata']['name']}")
            else:
                rc, out, _ = rd_local(pod, ns, op, "GET", "vkkey")
                if tok in out:
                    where.append(f"pod {pod['metadata']['name']}")
    if s["seed"]:
        rc, out, _ = K.node_sh(f"grep -rlF {tok} /var/local-path-provisioner /var/lib/kubelet/pods 2>/dev/null | head -5",
                               timeout=120)
        where += [f"node {x}" for x in out.split()]
    return where


# ---------------------------------------------------------------- exposure probes

def access(s, ns, ip):
    out = {}
    svcs = (K.kj("get", "svc", "-n", ns) or {"items": []})["items"]
    for sv in svcs:
        name = sv["metadata"]["name"]
        for p in sv["spec"].get("ports") or []:
            if p.get("nodePort"):
                rc, _, _ = K.sh(["docker", "exec", K.OUTSIDER, "nc", "-z", "-w", "2", ip, str(p["nodePort"])])
                out[f"external:{name}"] = out.get(f"external:{name}", False) or rc == 0
            if sv["spec"].get("clusterIP") not in (None, "None"):
                rc, _, _ = K.pexec(f"nc -z -w 2 {sv['spec']['clusterIP']} {p['port']}", ns="vk-outside")
                out[f"other-namespace:{name}"] = out.get(f"other-namespace:{name}", False) or rc == 0
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
    K.k("delete", "namespace", ns, "--wait=true", "--timeout=180s", timeout=200)
    K.k("delete", "clusterrolebinding,clusterrole", "-l", f"vk8s-scenario={ns}")
    pvs = (K.kj("get", "pv") or {"items": []})["items"]
    for pv in pvs:
        ref = pv["spec"].get("claimRef") or {}
        if ref.get("namespace") == ns:
            path = ((pv["spec"].get("hostPath") or pv["spec"].get("local") or {}).get("path"))
            K.k("delete", "pv", pv["metadata"]["name"], "--wait=true", "--timeout=60s")
            if path and path.startswith("/var/local-path-provisioner/"):
                K.node_sh(f"rm -rf {shlex.quote(path)}")


# ---------------------------------------------------------------- one scenario

def run(s):
    i = s["id"]
    ns = f"s{i}"
    d = os.path.join(RUNS, ns)
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    cleanup(ns)
    tok = f"tok{i}x{secrets.token_hex(4)}"
    res = {"id": i, "split": s["split"], "title": s["title"], "family": s["family"], "token": tok}
    pr = None
    try:
        rc, out, err = K.k("create", "namespace", ns)
        K.k("label", "namespace", ns, "vk8s=scenario")
        for n, st in enumerate(s["v1"]):
            rc, cmd, out = run_step(st, ns, d, f"v1-{n}", wait=True)
            if rc:
                raise RuntimeError(f"v1 {cmd}: {out[-1500:]}")
        if not wait_ready(ns):
            raise RuntimeError("v1 never became ready")
        for op in s["seed"]:
            seed(op, ns, tok)
        ip = K.node_ip()
        res["data_before"] = find_token(s, ns, tok) if s["seed"] else []
        if s["seed"] and not res["data_before"]:
            raise RuntimeError("seeded data not found before the change")
        res["access_before"] = access(s, ns, ip)
        fx = F.collect(s, ns, d)
        json.dump(fx, open(os.path.join(d, "facts.json"), "w"), indent=1)
        base = [baseline(p, ns) for p in s["probes"]]
        res["probe_baseline_ok"] = base
        live = [p for p, ok in zip(s["probes"], base) if ok]
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
        while time.time() - t0 < 90:
            if time.time() - t0 >= 3 and settled(ns):
                t_settle = time.time()
                break
            time.sleep(1)
        t1 = max(t0 + 20, (t_settle or time.time()) + 5)
        t1 = min(t1, t0 + 95)
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
        # data: give the service up to 60 s to come back before searching
        end = time.time() + 60
        while time.time() < end and live and not all(K.pexec(probe_cmd(p, ns))[0] == 0 for p in live):
            time.sleep(2)
        res["data_after"] = find_token(s, ns, tok) if s["seed"] else []
        res["access_after"] = access(s, ns, ip)
        newly = sorted(key for key, v in res["access_after"].items() if v and not res["access_before"].get(key))
        res["newly_accessible"] = newly
        res["labels"] = {"lost": bool(s["seed"]) and not res["data_after"],
                         "down": any(o["max_gap_s"] >= GAP for o in res["outage"]),
                         "exposed": bool(newly),
                         "failed": any(rcs)}
        if not any(base):
            raise RuntimeError("no probe passed its baseline")
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


BORDER = (1.0, 3.5)


def label(s):
    """Run once; if a probe's longest gap falls in the borderline band, run twice more and take the majority for down."""
    r = run(s)
    gaps = [o["max_gap_s"] for o in r.get("outage", [])]
    if r.get("labels") and any(BORDER[0] <= g <= BORDER[1] for g in gaps):
        reps = [r]
        for _ in range(2):
            x = run(s)
            if x.get("labels"):
                reps.append(x)
        downs = [x["labels"]["down"] for x in reps]
        r["borderline"] = {"gaps": [[o["max_gap_s"] for o in x["outage"]] for x in reps], "downs": downs,
                           "other_labels": [{k: v for k, v in x["labels"].items() if k != "down"} for x in reps]}
        r["labels"]["down"] = sum(downs) * 2 > len(downs)
        json.dump(r, open(os.path.join(RUNS, f"s{s['id']}", "result.json"), "w"), indent=1)
    return r


if __name__ == "__main__":
    ids = [int(x) for x in sys.argv[1:]] or [s["id"] for s in SC.S]
    for i in ids:
        t = time.time()
        r = label(SC.BY_ID[i])
        print(f"s{i:<3} {time.time() - t:5.0f}s {r.get('labels') or r.get('error')} "
              f"{[(o['max_gap_s'], o['fails']) for o in r.get('outage', [])]} {r.get('newly_accessible', '')} "
              f"rc={r.get('rcs')} {('border ' + str(r['borderline'])) if r.get('borderline') else ''}| {r['title']}",
              flush=True)
