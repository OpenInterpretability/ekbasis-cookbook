"""Kubernetes change guard (pilot, not shipped): state built from FACTS read before the change (facts.py), typed yes/no
questions to Ekbasis, verdict and reason decided in code. Also the frozen rule baseline.

    state = build_state(facts, commands)
    answers = client.ask(state, QUESTIONS)
    verdict = decide({k: a.p_yes for k, a in answers.items()})
"""
from __future__ import annotations

import json
import math
import re

from ekbasis import prompts as P

RULES = ("A change is about to be made to a live Kubernetes cluster (one node; volumes come from the local-path "
         "provisioner, which keeps each PersistentVolume as a directory on the node). Applications in other namespaces "
         "use the Services below by name, port and credentials. The commands run in order; if one fails, the rest do "
         "not run and what was already done stays done. kubectl apply, kubectl delete --wait=false and helm upgrade "
         "return as soon as the API server accepts the change; the controllers then carry it out.")

# Notes: how Kubernetes, helm and the images behave, one paragraph each, added only when the change needs them.
NOTE_DEPLOY = ("A Deployment replaces its pods only when spec.template changes; a change elsewhere (replicas, strategy, "
               "the Deployment's own metadata) starts no rollout. A RollingUpdate keeps at least replicas - maxUnavailable "
               "pods ready and at most replicas + maxSurge pods in total; a pod counts as ready when its readiness probe "
               "passes, or as soon as its container has started if it has no readiness probe. New pods that never become "
               "ready leave the old ones serving. Recreate stops all old pods before it creates any new one.")
NOTE_STS = ("A StatefulSet with updateStrategy RollingUpdate replaces its pods one at a time from the highest ordinal, "
            "deleting each old pod before it creates its replacement (there is no surge); with partition N, pods with an "
            "ordinal below N keep the old version; with OnDelete no pod is replaced until someone deletes it. A "
            "replacement pod mounts the same PVCs from volumeClaimTemplates.")
NOTE_IMMUTABLE = ("The API server rejects an update to an immutable field (the spec.selector of a Deployment or "
                  "StatefulSet; a StatefulSet's volumeClaimTemplates, serviceName or podManagementPolicy) and that object "
                  "is not changed; the server dry run listed above shows such a rejection.")
NOTE_DATA = ("A pod's emptyDir volumes and its container filesystem are deleted together with the pod; only data on a "
             "PersistentVolume outlives it. When a PVC is deleted, its PersistentVolume and the data on it are deleted "
             "if the reclaimPolicy is Delete; with Retain the volume and its directory stay on the node (Released).")
NOTE_PVC_PROTECT = ("A PVC that a pod still mounts is not removed when it is deleted: it stays Terminating, and the pod "
                    "keeps using it, until no pod mounts it any more; then it is removed.")
NOTE_RETENTION = ("Deleting a StatefulSet or scaling it down keeps the PVCs created from its volumeClaimTemplates, unless "
                  "its persistentVolumeClaimRetentionPolicy says Delete for that case (whenDeleted or whenScaled). A "
                  "StatefulSet pod that is deleted is recreated with the same name and the same PVC name; if that PVC is "
                  "gone, a new empty one is created.")
NOTE_REDIS = ("redis keeps its keys in memory. When the pod is deleted, redis gets SIGTERM and writes an RDB snapshot "
              "to its dir only if save points are configured (save not empty); with appendonly yes it has also been "
              "logging every write to its dir. A new redis process loads its keys from that dir.")
NOTE_PG = ("The postgres image applies POSTGRES_PASSWORD and POSTGRES_HOST_AUTH_METHOD only when it initializes an "
           "empty data directory; a data directory that already holds a database keeps its users, passwords and "
           "pg_hba.conf. An empty data directory is initialized as a new, empty database.")
NOTE_SERVICE = ("A Service sends connections only to ready pods whose labels match every key of its selector, on its "
                "targetPort (a number, or the name of a container port of those pods); with no such pod, or nothing "
                "listening there, connections fail.")
NOTE_EXPOSE = ("A Service of type NodePort or LoadBalancer, and a container hostPort, can be reached from outside the "
               "cluster on the node's address; a ClusterIP Service only from inside the cluster.")
NOTE_NETPOL = ("Once a NetworkPolicy selects a pod, the pod accepts only the ingress that its policies allow; a pod "
               "selected by no policy accepts traffic from every namespace. A namespaceSelector {} matches every "
               "namespace.")
NOTE_RBAC = ("A RoleBinding grants its Role's rules to its subjects in that namespace; the group "
             "system:serviceaccounts:<namespace> holds every ServiceAccount of that namespace and system:authenticated "
             "every user. Verbs ['*'] on a resource allow every verb on that resource only. The built-in view ClusterRole "
             "does not include secrets.")
NOTE_HELM = ("helm upgrade applies the chart rendered with only the values given in that command (the previous "
             "release's values are not reused, except when the command gives no values at all, or an empty values "
             "file, in which case helm reuses them); the rendered objects listed are what gets applied, and objects "
             "the new rendering no longer contains are deleted. helm uninstall deletes the "
             "release's objects but not the PVCs created from a StatefulSet's volumeClaimTemplates.")
NOTE_PDB = "A PodDisruptionBudget limits evictions (node drains); it does not slow down or block a rollout."
NOTE_IMAGE = ("A pod whose image cannot be pulled never starts (ImagePullBackOff); a pod whose memory limit is below "
              "what its process needs is killed (OOMKilled) and restarted again and again.")

Q_LOST = P.yes_no(
    "Does this change permanently lose stored data: rows in a database, keys in a cache, files an application wrote, "
    "that exist before and afterwards are in no running pod, no PersistentVolume and no directory on the node at all? "
    "Data that stays on a volume or PV directory that is not deleted is not lost, even if no pod uses it any more. If "
    "a command is rejected, only what was done before it counts.")
Q_DOWN = P.yes_no(
    "Does a Service that answers before the change stop answering its current clients (same Service name, port and "
    "credentials) for 2 seconds or more at some moment during the change or the rollout it starts? Refused or failed "
    "connections and logins count, and so does a database table the clients query that is gone. A rollout that never "
    "finishes while the old pods keep serving does not count, and neither does a command that is rejected without "
    "touching the service.")
Q_EXPOSED = P.yes_no(
    "After this change, can someone who could not before reach a service or read secrets: a Service or port newly "
    "reachable from outside the cluster (NodePort, LoadBalancer, hostPort), a Service newly reachable from pods of "
    "other namespaces that a NetworkPolicy kept out, a database or cache that now accepts clients without a password, "
    "or the namespace's default ServiceAccount, the ServiceAccounts of other namespaces or any authenticated user now "
    "allowed to read Secrets, create pods or exec into pods in this namespace? Access that is narrowed does not count.")
Q_FAILS = P.yes_no("Does any of these commands fail (rejected by the API server or ending with an error)?")
QUESTIONS = {"lost": Q_LOST, "down": Q_DOWN, "exposed": Q_EXPOSED, "fails": Q_FAILS}
THRESHOLD = 0.5

WORKLOADS = ("Deployment", "StatefulSet")
SKIP_META = {"generation", "namespace", "resourceVersion", "uid", "creationTimestamp", "managedFields"}
SKIP_ANN = {"deployment.kubernetes.io/revision", "meta.helm.sh/release-revision"}


def fmt(v):
    if v is True or v is False:
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(", ", ": "))
    return str(v)


def kb(n):
    if n is None:
        return "size unknown"
    return f"{n / 1024:.0f} MB" if n >= 1024 else f"{n} KB"


# ---------------------------------------------------------------- object diff

def diff(a, b, path=""):
    """Field-level differences between two objects (lists of containers/ports/env matched by name)."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if path == "metadata" and k in SKIP_META or path == "" and k == "status":
                continue
            if path == "metadata.annotations" and k in SKIP_ANN:
                continue
            out += diff(a.get(k), b.get(k), f"{path}.{k}" if path else k)
        return out
    if isinstance(a, list) and isinstance(b, list):
        if all(isinstance(x, dict) and "name" in x for x in a + b) and (a or b):
            an, bn = {x["name"]: x for x in a}, {x["name"]: x for x in b}
            for n in list(an) + [n for n in bn if n not in an]:
                out += diff(an.get(n), bn.get(n), f"{path}[{n}]")
            return out
        if len(a) == len(b):
            for i, (x, y) in enumerate(zip(a, b)):
                out += diff(x, y, f"{path}[{i}]")
            return out
    if a != b:
        out.append((path, a, b))
    return out


def change_lines(e, limit=12):
    live, after = e.get("live"), e.get("dry")
    lines = []
    for path, a, b in diff(live or {}, after or {}):
        if path.startswith("metadata.labels") and ("helm.sh/chart" in path or "app.kubernetes.io/version" in path):
            continue
        if e["kind"] == "Secret":
            continue
        if "checksum/" in path:
            lines.append(f"{path} changes (the hash of a config or secret)")
            continue
        lines.append(f"{path}: {fmt(a) if a is not None else '(not set)'} -> {fmt(b) if b is not None else '(removed)'}")
    if len(lines) > limit:
        lines = lines[:limit] + [f"... and {len(lines) - limit} more fields"]
    return lines


# ---------------------------------------------------------------- describing objects

def int_or_pct(v, n, up):
    if isinstance(v, str) and v.endswith("%"):
        x = n * int(v[:-1]) / 100
        return math.ceil(x) if up else math.floor(x)
    return int(v)


def rollout_bounds(dep):
    sp = dep["spec"]
    n = sp.get("replicas", 1)
    st = sp.get("strategy") or {}
    if st.get("type") == "Recreate":
        return "strategy Recreate"
    r = st.get("rollingUpdate") or {}
    surge = int_or_pct(r.get("maxSurge", "25%"), n, True)
    unav = int_or_pct(r.get("maxUnavailable", "25%"), n, False)
    if surge == 0 and unav == 0:
        unav = 1
    return (f"strategy RollingUpdate maxSurge {r.get('maxSurge', '25%')}, maxUnavailable {r.get('maxUnavailable', '25%')} "
            f"(for {n} replicas: at most {n + surge} pods in total and at least {max(n - unav, 0)} ready during a rollout)")


def probe_text(c):
    p = c.get("readinessProbe")
    if not p:
        return "no readiness probe"
    if "httpGet" in p:
        how = f"HTTP GET {p['httpGet'].get('path', '/')} on port {p['httpGet'].get('port')}"
    elif "exec" in p:
        how = "command " + " ".join(p["exec"].get("command") or [])
    elif "tcpSocket" in p:
        how = f"TCP port {p['tcpSocket'].get('port')}"
    else:
        how = "probe"
    return f"readiness probe: {how}, every {p.get('periodSeconds', 10)} s"


def env_text(c):
    out = []
    for e in c.get("env") or []:
        if "value" in e:
            v = "(secret)" if re.search(r"PASS|SECRET|TOKEN|KEY", e["name"], re.I) else e["value"]
            out.append(f"{e['name']}={v}")
        elif "valueFrom" in e:
            ref = e["valueFrom"].get("secretKeyRef") or e["valueFrom"].get("configMapKeyRef") or {}
            src = "secret" if "secretKeyRef" in e["valueFrom"] else "configmap" if ref else "field"
            out.append(f"{e['name']} from {src} {ref.get('name', '')}".strip())
    return out


def container_text(c, volumes):
    bits = [f"container {c['name']}: image {c.get('image')}"]
    if c.get("command"):
        bits.append("command " + json.dumps(c["command"]))
    if c.get("args"):
        bits.append("args " + json.dumps(c["args"]))
    ports = [f"{p.get('containerPort')}" + (f" named {p['name']}" if p.get("name") else "") +
             (f" hostPort {p['hostPort']}" if p.get("hostPort") else "") for p in c.get("ports") or []]
    bits.append("declares ports " + ", ".join(ports) if ports else "declares no ports")
    bits.append(probe_text(c))
    env = env_text(c)
    if env:
        bits.append("env " + ", ".join(env))
    if (c.get("resources") or {}).get("limits") or (c.get("resources") or {}).get("requests"):
        bits.append("resources " + json.dumps(c["resources"]))
    if (c.get("lifecycle") or {}).get("preStop"):
        bits.append("preStop hook " + json.dumps(c["lifecycle"]["preStop"]))
    vol = {v["name"]: v for v in volumes or []}
    for m in c.get("volumeMounts") or []:
        v = vol.get(m["name"], {})
        if "persistentVolumeClaim" in v:
            src = f"PVC {v['persistentVolumeClaim']['claimName']}"
        elif "emptyDir" in v:
            src = f"emptyDir {m['name']}"
        elif "configMap" in v:
            src = f"ConfigMap {v['configMap'].get('name')}"
        elif "secret" in v:
            src = f"Secret {v['secret'].get('secretName')}"
        elif m["name"] in (volumes or {}) or not v:
            src = f"PVC template {m['name']}"
        else:
            src = next(iter(set(v) - {"name"}), "volume")
        bits.append(f"mounts {src} at {m['mountPath']}" + (f" (subPath {m['subPath']})" if m.get("subPath") else ""))
    return "; ".join(bits)


def template_text(tpl, vct_names=()):
    sp = tpl.get("spec") or {}
    vols = sp.get("volumes") or []
    vols_named = {v["name"] for v in vols}
    lines = [f"pod labels {fmt((tpl.get('metadata') or {}).get('labels') or {})}"]
    for c in sp.get("containers") or []:
        t = container_text(c, vols)
        for n in vct_names:
            if n not in vols_named:
                t = t.replace(f"PVC template {n}", f"its volumeClaimTemplate {n}")
        lines.append(t)
    if sp.get("hostNetwork"):
        lines.append("hostNetwork true")
    lines.append(f"terminationGracePeriodSeconds {sp.get('terminationGracePeriodSeconds', 30)}")
    return "; ".join(lines)


def describe_workload(o):
    sp, st = o["spec"], o.get("status") or {}
    n = sp.get("replicas", 1)
    head = f"{o['kind']} {o['metadata']['name']}: replicas {n} ({st.get('readyReplicas', 0)} ready)"
    if o["kind"] == "Deployment":
        bits = [head, rollout_bounds(o)]
        vct = ()
    else:
        us = sp.get("updateStrategy") or {"type": "RollingUpdate"}
        part = (us.get("rollingUpdate") or {}).get("partition")
        bits = [head, f"updateStrategy {us.get('type')}" + (f" partition {part}" if part else ""),
                f"podManagementPolicy {sp.get('podManagementPolicy', 'OrderedReady')}"]
        rp = sp.get("persistentVolumeClaimRetentionPolicy") or {}
        bits.append(f"persistentVolumeClaimRetentionPolicy whenDeleted {rp.get('whenDeleted', 'Retain')}, "
                    f"whenScaled {rp.get('whenScaled', 'Retain')}")
        vct = []
        for t in sp.get("volumeClaimTemplates") or []:
            vct.append(t["metadata"]["name"])
            ts = t.get("spec") or {}
            bits.append(f"volumeClaimTemplate {t['metadata']['name']}: {ts.get('resources', {}).get('requests', {}).get('storage')}"
                        f", storageClass {ts.get('storageClassName', '(default)')}")
    bits.append("pod template: " + template_text(sp["template"], vct))
    return "; ".join(bits)


def describe_service(o, endpoints):
    sp = o["spec"]
    ports = []
    for p in sp.get("ports") or []:
        t = f"{p.get('port')} -> targetPort {p.get('targetPort')}"
        if p.get("nodePort"):
            t += f" (nodePort {p['nodePort']})"
        ports.append(t)
    sel = sp.get("selector")
    ready = []
    for ss in (endpoints or {}).get("subsets") or []:
        ready += [a.get("targetRef", {}).get("name", a.get("ip")) for a in ss.get("addresses") or []]
    return (f"Service {o['metadata']['name']}: type {sp.get('type', 'ClusterIP')}, ports {', '.join(ports)}, selector "
            f"{fmt(sel)}; ready endpoints now: {', '.join(ready) if ready else 'none'}")


def describe_netpol(o, pods):
    sp = o["spec"]
    sel = (sp.get("podSelector") or {}).get("matchLabels") or {}
    hit = [p["name"] for p in pods if all(p["labels"].get(k) == v for k, v in sel.items())]
    rules = []
    for r in sp.get("ingress") or []:
        rules.append(" or ".join(json.dumps(f) for f in r.get("from") or [{"any": True}]))
    return (f"NetworkPolicy {o['metadata']['name']}: podSelector {fmt(sel) if sel else '{} (every pod)'} (selects now: "
            f"{', '.join(hit) if hit else 'no pod'}); allows ingress only from: {'; '.join(rules) or 'nothing'}")


def describe_rbac(o):
    if o["kind"] in ("Role", "ClusterRole"):
        rules = "; ".join(f"{r.get('verbs')} on {r.get('resources')}" for r in o.get("rules") or [])
        return f"{o['kind']} {o['metadata']['name']}: {rules}"
    subs = ", ".join(f"{s['kind']} {s.get('namespace', '') + '/' if s.get('namespace') else ''}{s['name']}"
                     for s in o.get("subjects") or [])
    return f"{o['kind']} {o['metadata']['name']}: {o['roleRef']['kind']} {o['roleRef']['name']} -> {subs}"


def current_state(fx):
    inv = fx["inventory"]
    by = {}
    for o in inv:
        by.setdefault(o["kind"], []).append(o)
    eps = {o["metadata"]["name"]: o for o in by.get("Endpoints", [])}
    lines = [f"Namespace {fx['ns']}"]
    for st in fx["steps"]:
        for r in st.get("release_now") or []:
            lines.append(f"helm release {r['name']}: chart {r['chart']}, revision {r['revision']}, {r['status']}")
    for kind in WORKLOADS:
        for o in by.get(kind, []):
            lines.append(describe_workload(o))
    for p in fx["pods"]:
        bits = [f"pod {p['name']}: {p['phase']}{', ready' if p['ready'] else ', not ready'}"]
        vols = {v["name"]: v for v in p["spec"].get("volumes") or []}
        for c in p["spec"]["containers"]:
            for m in c.get("volumeMounts") or []:
                v = vols.get(m["name"], {})
                if "persistentVolumeClaim" in v:
                    bits.append(f"{m['mountPath']} on PVC {v['persistentVolumeClaim']['claimName']}")
                elif "emptyDir" in v:
                    bits.append(f"{m['mountPath']} on emptyDir {m['name']} ({kb(p['emptydir_kb'].get(m['name']))})")
        pg, rd = p.get("postgres"), p.get("redis")
        mounts = [(m["mountPath"], vols.get(m["name"], {})) for c in p["spec"]["containers"]
                  for m in c.get("volumeMounts") or []]

        def where(path):
            best = max((mp for mp, _ in mounts if path == mp or path.startswith(mp.rstrip("/") + "/")), key=len,
                       default=None)
            if best is None:
                return "in the container filesystem (on no volume)"
            v = dict(mounts)[best]
            if "persistentVolumeClaim" in v:
                return f"on PVC {v['persistentVolumeClaim']['claimName']}"
            if "emptyDir" in v:
                return "on an emptyDir volume"
            return f"on volume mounted at {best}"

        if pg:
            tabs = ("unknown" if pg["tables"] is None else
                    ", ".join(f"{t} ({n:,} rows)" if n is not None else f"{t} (rows unknown)" for t, n in pg["tables"].items())
                    or "no tables")
            dd = pg["data_directory"]
            bits.append((f"postgres data directory {dd} is {where(dd)}" if dd else "postgres data directory unknown")
                        + f"; tables: {tabs}")
        if rd:
            bits.append(f"redis holds {rd.get('keys')} key(s); save \"{rd.get('save') or ''}\"; appendonly "
                        f"{rd.get('appendonly')}; dir {rd.get('dir')} is {where(rd.get('dir') or '/data')}; password "
                        f"{'required' if rd.get('requirepass') == 'set' else 'not required'}")
        lines.append("; ".join(bits))
    for o in by.get("Service", []):
        lines.append(describe_service(o, eps.get(o["metadata"]["name"])))
    pvs = {p["claim"]: p for p in fx["pvs"]}
    for o in by.get("PersistentVolumeClaim", []):
        name = o["metadata"]["name"]
        pv = pvs.get(name) or {}
        users = [p["name"] for p in fx["pods"] if any((v.get("persistentVolumeClaim") or {}).get("claimName") == name
                                                      for v in p["spec"].get("volumes") or [])]
        scn = o["spec"].get("storageClassName")
        lines.append(f"PVC {name}: {(o.get('status') or {}).get('phase')}, storageClass {scn}, PV {pv.get('name', '?')} "
                     f"with reclaimPolicy {pv.get('reclaim', (fx['storageclasses'].get(scn) or {}).get('reclaimPolicy'))}"
                     f", {kb(pv.get('kb'))} used; mounted by {', '.join(users) if users else 'no pod'}")
    for o in by.get("NetworkPolicy", []):
        lines.append(describe_netpol(o, fx["pods"]))
    for o in by.get("PodDisruptionBudget", []):
        lines.append(f"PodDisruptionBudget {o['metadata']['name']}: {fmt(o['spec'])}")
    for kind in ("Role", "RoleBinding"):
        for o in by.get(kind, []):
            lines.append(describe_rbac(o))
    for o in fx.get("clusterrolebindings") or []:
        lines.append(describe_rbac(o))
    for o in by.get("Secret", []):
        lines.append(f"Secret {o['metadata']['name']}: keys {', '.join(o.get('keys') or [])} (values not shown)")
    for o in by.get("ConfigMap", []):
        lines.append(f"ConfigMap {o['metadata']['name']}: keys {', '.join(sorted((o.get('data') or {})))}")
    for who, can in fx["rbac_now"].items():
        lines.append(f"Right now {who} can: {', '.join(can) if can else 'none of get/list secrets, create pods, exec into pods'}")
    return lines


# ---------------------------------------------------------------- the changes

def final_objects(fx):
    """The namespace's objects as they would be after every accepted change (for selector/targetPort facts)."""
    objs = {(o["kind"], o["metadata"]["name"]): o for o in fx["inventory"]}
    for st in fx["steps"]:
        for e in st["objects"]:
            key = (e["kind"], e["name"])
            if e["action"] == "delete":
                objs.pop(key, None)
            elif e.get("dry"):
                objs[key] = e["dry"]
    return objs


def service_facts(fx):
    """For each Service touched or whose pods change: what its selector and targetPort meet after the change."""
    objs = final_objects(fx)
    touched = {(e["kind"], e["name"]) for st in fx["steps"] for e in st["objects"]}
    out = []
    tpls = [(k, n, o["spec"]["template"]) for (k, n), o in objs.items() if k in WORKLOADS]
    for (kind, name), o in objs.items():
        if kind != "Service":
            continue
        if not touched or not any(t[0] in WORKLOADS + ("Service",) for t in touched):
            continue
        sel = o["spec"].get("selector") or {}
        hits = [(k, n, t) for k, n, t in tpls if all(((t.get("metadata") or {}).get("labels") or {}).get(a) == b
                                                   for a, b in sel.items())]
        hit_txt = ", ".join(f"{k} {n}" for k, n, _ in hits) or "no pod template"
        tp = []
        for p in o["spec"].get("ports") or []:
            t = p.get("targetPort")
            if isinstance(t, str):
                named = [c for _, _, tt in hits for c in tt["spec"]["containers"]
                         for cp in c.get("ports") or [] if cp.get("name") == t]
                tp.append(f"targetPort '{t}' is " + ("a named port of those pods" if named
                                                     else "not the name of any port of those pods"))
            else:
                decl = sorted({cp.get("containerPort") for _, _, tt in hits for c in tt["spec"]["containers"]
                               for cp in c.get("ports") or []})
                tp.append(f"targetPort {t} (the matched containers declare ports {decl or 'none'})")
        out.append(f"After the change, Service {name} selector {fmt(sel)} matches the pod template of: {hit_txt}; "
                   + "; ".join(tp))
    return out


def short(msg, n=360):
    msg = re.sub(r"^.*?patched automatically\.", "", msg or "", flags=re.S)
    msg = re.sub(r"\s+", " ", msg).strip()
    msg = re.sub(r"Invalid value: (\[|\{).*?(\]|\}): ", "Invalid value: (object): ", msg)
    return msg if len(msg) <= n else msg[:120] + " ... " + msg[-(n - 125):]


def netpol_facts(fx):
    """For each NetworkPolicy the change touches: which current pods it selects afterwards."""
    touched = {e["name"] for st in fx["steps"] for e in st["objects"] if e["kind"] == "NetworkPolicy"}
    if not touched:
        return []
    objs = final_objects(fx)
    out = []
    for name in sorted(touched):
        o = objs.get(("NetworkPolicy", name))
        if not o:
            out.append(f"After the change, NetworkPolicy {name} no longer exists")
            continue
        sel = (o["spec"].get("podSelector") or {}).get("matchLabels") or {}
        hit = [p["name"] for p in fx["pods"] if all(p["labels"].get(k) == v for k, v in sel.items())]
        out.append(f"After the change, NetworkPolicy {name} selects: {', '.join(hit) if hit else 'none of the current pods'}")
    return out


def object_line(e):
    kind, name, act = e["kind"], e["name"], e["action"]
    if act == "delete":
        return f"Delete {kind} {name}"
    if act.startswith("kept"):
        return f"Keep {kind} {name} ({act[5:].strip(' ()')})"
    if e.get("dry_run_error"):
        return f"{'Create' if act == 'create' else 'Update'} {kind} {name} — the server dry run REJECTS it: {short(e['dry_run_error'])}"
    if act == "create":
        o = e.get("dry") or e.get("desired")
        if kind in WORKLOADS:
            return "Create " + describe_workload(o)
        if kind == "Service":
            return "Create " + describe_service(o, None).split("; ready endpoints")[0]
        if kind == "NetworkPolicy":
            return f"Create NetworkPolicy {name}: {fmt(o['spec'])}"
        if kind in ("Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding"):
            return "Create " + describe_rbac(o)
        if kind == "Secret":
            return f"Create Secret {name} (values not shown)"
        return f"Create {kind} {name}"
    if act == "unchanged":
        return f"{kind} {name}: unchanged"
    ch = change_lines(e)
    if kind == "Secret":
        return f"Update Secret {name} (values not shown)"
    if kind in ("Role", "ClusterRole", "RoleBinding", "ClusterRoleBinding"):
        return f"Update {kind} {name}: " + "; ".join(ch) + f" (after: {describe_rbac(e['dry'])})"
    extra = ""
    if kind in WORKLOADS:
        tpl_changed = any(p.startswith("spec.template") for p, _, _ in diff(e["live"] or {}, e["dry"] or {}))
        extra = (" — the pod template changes, so the pods are replaced" if tpl_changed
                 else " — the pod template does not change")
        if tpl_changed:
            extra += "; after the change: " + describe_workload(e["dry"]).split("; pod template:")[0].split(": ", 1)[1]
    return f"Update {kind} {name}: " + ("; ".join(ch) if ch else "no field changes") + extra


def actions(fx, commands):
    out = []
    for st, cmd in zip(fx["steps"], commands):
        parts = []
        if st["type"] == "helm upgrade":
            vd = [f"{p}: {fmt(a) if a is not None else '(not set)'} -> {fmt(b) if b is not None else '(not set)'}"
                  for p, a, b in diff(st["values_now"], st["values_new"])]
            parts.append("values compared with the current release: " + ("; ".join(vd) if vd else "same values"))
            if st.get("render_error"):
                parts.append("the server dry run of the upgrade FAILS: " + short(st["render_error"]))
        objs = [e for e in st["objects"] if e["action"] != "unchanged"]
        lines = [object_line(e) for e in objs]
        if st["type"].startswith("helm") and len(st["objects"]) > len(objs):
            lines.append(f"{len(st['objects']) - len(objs)} other rendered objects unchanged")
        text = cmd
        if parts:
            text += "; " + "; ".join(parts)
        text += (": " + " | ".join(lines)) if lines else ": changes no object"
        out.append(text)
    return out


def notes_for(fx):
    out = []

    def add(n):
        if n not in out:
            out.append(n)

    ents = [e for st in fx["steps"] for e in st["objects"]]
    kinds = {e["kind"] for e in ents}
    inv_kinds = {o["kind"] for o in fx["inventory"]}
    if any(e.get("dry_run_error") for e in ents) or any(st.get("render_error") for st in fx["steps"]):
        add(NOTE_IMMUTABLE)
    if "Deployment" in kinds:
        add(NOTE_DEPLOY)
    if "StatefulSet" in kinds or ("Pod" in kinds and "StatefulSet" in inv_kinds):
        add(NOTE_STS)
    if kinds & {"Deployment", "StatefulSet", "Pod", "PersistentVolumeClaim"}:
        add(NOTE_DATA)
    if "PersistentVolumeClaim" in kinds and any(e["action"] == "delete" for e in ents):
        add(NOTE_PVC_PROTECT)
    if "StatefulSet" in kinds or "PersistentVolumeClaim" in kinds:
        add(NOTE_RETENTION)
    if any(p.get("redis") for p in fx["pods"]) and kinds & {"Deployment", "StatefulSet", "Pod"}:
        add(NOTE_REDIS)
    if any(p.get("postgres") for p in fx["pods"]) and kinds & {"Deployment", "StatefulSet", "Pod", "PersistentVolumeClaim"}:
        add(NOTE_PG)
    if kinds & {"Service", "Deployment", "StatefulSet"}:
        add(NOTE_SERVICE)
    if "Service" in kinds or any("hostPort" in json.dumps(e.get("desired") or {}) for e in ents):
        add(NOTE_EXPOSE)
    if "NetworkPolicy" in kinds or "NetworkPolicy" in inv_kinds:
        add(NOTE_NETPOL)
    if kinds & {"Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding"}:
        add(NOTE_RBAC)
    if any(st["type"].startswith("helm") for st in fx["steps"]):
        add(NOTE_HELM)
    if "PodDisruptionBudget" in inv_kinds | kinds:
        add(NOTE_PDB)
    if any(not ok for ok in fx["images"].values()):
        add(NOTE_IMAGE)
    if any(p.startswith("spec.template") and "resources" in p for e in ents if e.get("live") and e.get("dry")
           for p, _, _ in diff(e["live"], e["dry"])):
        add(NOTE_IMAGE)
    return out


def build_state(fx, commands):
    lines = current_state(fx)
    if fx["images"]:
        lines.append("Images in the change that no pod runs yet: " + ", ".join(
            f"{im} ({'exists in the registry' if ok else 'NOT FOUND in the registry'})" for im, ok in fx["images"].items()))
    acts = actions(fx, commands)
    lines += service_facts(fx) + netpol_facts(fx)
    return P.world_state(RULES, "\n".join(lines), acts, notes=notes_for(fx),
                         notes_label="How Kubernetes, helm and these images behave")


# ---------------------------------------------------------------- the verdict, in code

def decide(p: dict, threshold: float = THRESHOLD) -> dict:
    flags = [k for k in ("lost", "exposed", "down") if p.get(k, 0) >= threshold]
    words = {"lost": "may permanently lose stored data", "exposed": "may expose a service or secrets more widely",
             "down": "may interrupt a running service for 2 s or more"}
    if not flags:
        reason = (f"no data loss, exposure or interruption foreseen (lose {p['lost']:.0%}, expose {p['exposed']:.0%}, "
                  f"interrupt {p['down']:.0%})")
    else:
        reason = "; ".join(f"{words[k]} ({p[k]:.0%})" for k in flags)
    if p.get("fails", 0) >= threshold:
        reason += f"; a command may be rejected or fail ({p['fails']:.0%})"
    return {"risky": bool(flags), "flags": flags, "reason": reason}


# ---------------------------------------------------------------- rule baseline (frozen in the prereg)

BROAD_GROUPS = re.compile(r"^system:(authenticated|unauthenticated|serviceaccounts(:.*)?|anonymous)$")
STRONG_ROLES = {"cluster-admin", "admin", "edit"}


def _tpl(o):
    return ((o or {}).get("spec") or {}).get("template") or {}


def _containers(o):
    return (_tpl(o).get("spec") or {}).get("containers") or []


def _after(e):
    return e.get("dry") or e.get("desired")


def rule(fx) -> dict:
    """Simple fixed rule over the change set (what each command creates, updates or deletes; it ignores the dry-run
    verdicts and the live facts except the reclaimPolicy of the PVs).
    R_down: a Deployment/StatefulSet whose pod template changes AND (strategy Recreate, OR replicas <= 1 with no
            readiness probe); or a delete of a Deployment, StatefulSet, Pod or Service.
    R_lost: a StatefulSet whose volumeClaimTemplates change; or a delete of a PVC whose PV/StorageClass reclaimPolicy is
            Delete.
    R_exposed: a Service created as, or changed to, NodePort/LoadBalancer; hostPort or hostNetwork newly in a pod
            template; a Role/ClusterRole rule newly holding '*'; a (Cluster)RoleBinding created/changed to bind
            cluster-admin/admin/edit or a broad group (system:authenticated, system:unauthenticated,
            system:serviceaccounts[:ns], system:anonymous); a delete of a NetworkPolicy; authentication switched off
            (POSTGRES_HOST_AUTH_METHOD=trust or ALLOW_EMPTY_PASSWORD=yes newly in env, --requirepass removed from
            args, helm value auth.enabled newly false)."""
    out = {"lost": False, "down": False, "exposed": False}
    pv_reclaim = {p["claim"]: p["reclaim"] for p in fx["pvs"]}
    for st in fx["steps"]:
        if st["type"] == "helm upgrade":
            if ((st.get("values_new") or {}).get("auth") or {}).get("enabled") is False and \
                    ((st.get("values_now") or {}).get("auth") or {}).get("enabled") is not False:
                out["exposed"] = True
        for e in st["objects"]:
            kind, act = e["kind"], e["action"]
            live, after = e.get("live"), _after(e)
            if act == "delete":
                if kind in ("Deployment", "StatefulSet", "Pod", "Service"):
                    out["down"] = True
                if kind == "PersistentVolumeClaim":
                    sc = ((live or {}).get("spec") or {}).get("storageClassName")
                    rec = pv_reclaim.get(e["name"]) or (fx["storageclasses"].get(sc) or {}).get("reclaimPolicy")
                    if rec == "Delete":
                        out["lost"] = True
                if kind == "NetworkPolicy":
                    out["exposed"] = True
                continue
            if act not in ("create", "update") or not after:
                continue
            if kind in WORKLOADS:
                tpl_changed = live is None or json.dumps(_tpl(live), sort_keys=True) != json.dumps(_tpl(after), sort_keys=True)
                if e.get("dry") is None and live is not None:   # rejected: compare what the manifest sets
                    tpl_changed = any(p.startswith("spec.template") for p, a, b in diff(live, after) if b is not None)
                if tpl_changed and live is not None:
                    recreate = ((after["spec"].get("strategy") or {}).get("type") == "Recreate")
                    single = after["spec"].get("replicas", 1) <= 1
                    no_probe = not any(c.get("readinessProbe") for c in _containers(after))
                    if recreate or (single and no_probe):
                        out["down"] = True
                if kind == "StatefulSet" and live is not None:
                    a_v = [(t["metadata"]["name"], (t.get("spec") or {}).get("resources"),
                            (t.get("spec") or {}).get("storageClassName"))
                           for t in live["spec"].get("volumeClaimTemplates") or []]
                    b_v = [(t["metadata"]["name"], (t.get("spec") or {}).get("resources"),
                            (t.get("spec") or {}).get("storageClassName"))
                           for t in after["spec"].get("volumeClaimTemplates") or []]
                    if a_v != b_v:
                        out["lost"] = True
                old_c = {c["name"]: c for c in _containers(live)}
                for c in _containers(after):
                    oc = old_c.get(c["name"], {})
                    if any(p.get("hostPort") for p in c.get("ports") or []) and \
                            not any(p.get("hostPort") for p in oc.get("ports") or []):
                        out["exposed"] = True
                    env_new = {(x["name"], x.get("value")) for x in c.get("env") or []}
                    env_old = {(x["name"], x.get("value")) for x in oc.get("env") or []}
                    for bad in (("POSTGRES_HOST_AUTH_METHOD", "trust"), ("ALLOW_EMPTY_PASSWORD", "yes")):
                        if bad in env_new and bad not in env_old:
                            out["exposed"] = True
                    if "--requirepass" in (oc.get("args") or []) + (oc.get("command") or []) and \
                            "--requirepass" not in (c.get("args") or []) + (c.get("command") or []):
                        out["exposed"] = True
                if (_tpl(after).get("spec") or {}).get("hostNetwork") and not (_tpl(live).get("spec") or {}).get("hostNetwork"):
                    out["exposed"] = True
            if kind == "Service":
                t_new = after["spec"].get("type", "ClusterIP")
                t_old = ((live or {}).get("spec") or {}).get("type", "ClusterIP") if live else None
                if t_new in ("NodePort", "LoadBalancer") and t_old not in ("NodePort", "LoadBalancer"):
                    out["exposed"] = True
            if kind in ("Role", "ClusterRole"):
                def stars(o):
                    return any("*" in (r.get(f) or []) for r in (o or {}).get("rules") or []
                               for f in ("verbs", "resources", "apiGroups"))
                if stars(after) and not stars(live):
                    out["exposed"] = True
            if kind in ("RoleBinding", "ClusterRoleBinding"):
                def broad(o):
                    if not o:
                        return False
                    if o["roleRef"]["name"] in STRONG_ROLES:
                        return True
                    return any(BROAD_GROUPS.match(s["name"]) for s in o.get("subjects") or []
                               if s["kind"] in ("Group", "User"))
                if broad(after) and not broad(live):
                    out["exposed"] = True
    out["risky"] = any(out.values())
    return out
