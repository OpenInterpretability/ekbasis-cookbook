"""Live facts a guard can read safely BEFORE the change (read-only): the objects each command touches (live object,
the desired object, and the API server's dry-run answer, as `kubectl diff` does), the helm release manifest and the
rendered upgrade, and the namespace around them: workloads, pods and their volumes, Services and endpoints, PVCs, PVs,
StorageClasses and how full the volumes are, NetworkPolicies, PDBs, RBAC (what three identities can do now), the redis
persistence settings and the postgres tables (row counts) read through the pods, and whether new images exist.
Secret values are never stored: Secret data is dropped and helm values whose key looks secret are redacted.
Collected raw here; guard.py renders them."""
from __future__ import annotations

import json
import re
import shlex

import yaml

import kube as K

SECRET_KEY = re.compile(r"pass|secret|token|key", re.I)
IDENTITIES = {"the namespace's default ServiceAccount": ["--as=system:serviceaccount:{ns}:default"],
              "the default ServiceAccount of another namespace": ["--as=system:serviceaccount:vk-outside:default"],
              "any authenticated user": ["--as=vk-random-user", "--as-group=system:authenticated"]}
VERBS = [("get", "secrets"), ("list", "secrets"), ("create", "pods"), ("create", "pods/exec")]
KINDS = "deploy,sts,svc,endpoints,pvc,networkpolicy,pdb,role,rolebinding,configmap,secret,serviceaccount"


def clean(o):
    """Drop noise (managedFields, last-applied, status of non-workloads) and secret values."""
    if not o:
        return o
    o = json.loads(json.dumps(o))
    md = o.get("metadata") or {}
    for f in ("managedFields", "resourceVersion", "uid", "creationTimestamp", "selfLink"):
        md.pop(f, None)
    ann = md.get("annotations") or {}
    ann.pop("kubectl.kubernetes.io/last-applied-configuration", None)
    if not ann:
        md.pop("annotations", None)
    if o.get("kind") == "Secret":
        keys = sorted(set((o.get("data") or {})) | set((o.get("stringData") or {})))
        o.pop("data", None)
        o.pop("stringData", None)
        o["keys"] = keys
    return o


def redact_values(v, path=""):
    if isinstance(v, dict):
        return {k: ("(secret)" if SECRET_KEY.search(k) and not isinstance(x, (dict, list, bool)) else
                    redact_values(x, f"{path}.{k}")) for k, x in v.items()}
    if isinstance(v, list):
        return [redact_values(x, path) for x in v]
    return v


def get(kind, name, ns):
    return K.kj("get", kind, name, "-n", ns)


def dry_run(obj, ns):
    rc, out, err = K.k("apply", "--dry-run=server", "-n", ns, "-o", "json", "-f", "-", stdin=json.dumps(obj))
    if rc:
        return None, (err or out).strip()[-800:]
    try:
        return json.loads(out), None
    except ValueError:
        return None, out[-300:]


def obj_entry(obj, ns, action=None):
    kind, name = obj["kind"], obj["metadata"]["name"]
    live = get(kind, name, ns)
    e = {"kind": kind, "name": name, "live": clean(live), "desired": clean(obj)}
    if action == "delete":
        e["action"] = "delete"
        return e
    dry, err = dry_run(obj, ns)
    e["dry_run_error"] = err
    e["dry"] = clean(dry)
    if live is None:
        e["action"] = "create"
    else:
        a, b = strip_for_compare(live), strip_for_compare(dry) if dry else None
        e["action"] = "unchanged" if b is not None and a == b else "update"
    return e


def strip_for_compare(o):
    o = clean(o)
    if not o:
        return o
    o.pop("status", None)
    md = o.get("metadata") or {}
    md.pop("generation", None)
    return o


def manifest_objs(text):
    return [d for d in yaml.safe_load_all(text or "") if d and d.get("kind")]


def collect_steps(s, ns, d):
    steps = []
    for n, st in enumerate(s["v2"]):
        if "apply" in st:
            objs = [K.render(o, ns) for o in st["apply"]]
            steps.append({"type": "kubectl apply", "objects": [obj_entry(o, ns) for o in objs]})
        elif "delete" in st:
            objs = []
            for kind, name in st["delete"]:
                live = K.kj("get", kind, name, "-n", ns)
                objs.append({"kind": live["kind"] if live else kind, "name": name, "action": "delete",
                             "live": clean(live)})
            steps.append({"type": "kubectl delete", "objects": objs})
        elif "helm" in st:
            h = st["helm"]
            vf = f"{d}/v2-values-dry.json"
            json.dump(h["values"], open(vf, "w"))
            cur_vals = json.loads(K.helm("get", "values", h["release"], "-n", ns, "-o", "json")[1] or "{}")
            cur_man = manifest_objs(K.helm("get", "manifest", h["release"], "-n", ns)[1])
            rel = json.loads(K.helm("list", "-n", ns, "-o", "json")[1] or "[]")
            rc, out, err = K.helm("upgrade", h["release"], K.chart_path(h["chart"]), "-n", ns, "-f", vf,
                                  "--dry-run=server", "-o", "json")
            e = {"type": "helm upgrade", "release": h["release"], "chart": h["chart"],
                 "release_now": [{k: r.get(k) for k in ("name", "revision", "status", "chart", "app_version")}
                                 for r in rel if r.get("name") == h["release"]],
                 "values_now": redact_values(cur_vals), "values_new": redact_values(h["values"])}
            if rc:
                e["render_error"] = (err or out)[-800:]
                e["objects"] = []
            else:
                new = manifest_objs(json.loads(out).get("manifest", ""))
                for o in new:
                    o.setdefault("metadata", {})["namespace"] = ns
                key = {(o["kind"], o["metadata"]["name"]) for o in new}
                e["objects"] = [obj_entry(o, ns) for o in new]
                e["objects"] += [obj_entry(dict(o, metadata=dict(o["metadata"], namespace=ns)), ns, "delete")
                                 for o in cur_man if (o["kind"], o["metadata"]["name"]) not in key]
            steps.append(e)
        elif "helm_uninstall" in st:
            rel = st["helm_uninstall"]
            cur_man = manifest_objs(K.helm("get", "manifest", rel, "-n", ns)[1])
            e = {"type": "helm uninstall", "release": rel, "objects": []}
            for o in cur_man:
                keep = ((o.get("metadata") or {}).get("annotations") or {}).get("helm.sh/resource-policy") == "keep"
                ent = obj_entry(dict(o, metadata=dict(o["metadata"], namespace=ns)), ns, "delete")
                if keep:
                    ent["action"] = "kept (helm.sh/resource-policy: keep)"
                e["objects"].append(ent)
            steps.append(e)
    return steps


def pv_usage(pv):
    path = ((pv["spec"].get("hostPath") or pv["spec"].get("local") or {}).get("path"))
    if not path:
        return None
    rc, out, _ = K.node_sh(f"du -sk {shlex.quote(path)} 2>/dev/null")
    return int(out.split()[0]) if rc == 0 and out.strip() else None


def emptydir_usage(pod, vol):
    uid = pod["metadata"]["uid"]
    rc, out, _ = K.node_sh(f"du -sk /var/lib/kubelet/pods/{uid}/volumes/kubernetes.io~empty-dir/{vol} 2>/dev/null")
    return int(out.split()[0]) if rc == 0 and out.strip() else None


def redis_config(pod, ns, pw):
    out = {}
    for key in ("save", "appendonly", "dir", "requirepass"):
        c = f"redis-cli -a {shlex.quote(pw)} --no-auth-warning CONFIG GET {key} 2>/dev/null || redis-cli CONFIG GET {key}"
        rc, o, _ = K.k("exec", "-n", ns, pod["metadata"]["name"], "-c", pod["spec"]["containers"][0]["name"], "--",
                       "sh", "-c", c)
        lines = o.strip().splitlines()
        val = lines[1] if len(lines) > 1 else None
        out[key] = ("set" if val else "empty") if key == "requirepass" else val
    rc, o, _ = K.k("exec", "-n", ns, pod["metadata"]["name"], "-c", pod["spec"]["containers"][0]["name"], "--", "sh", "-c",
                   f"redis-cli -a {shlex.quote(pw)} --no-auth-warning DBSIZE 2>/dev/null || redis-cli DBSIZE")
    out["keys"] = o.strip().splitlines()[-1] if o.strip() else None
    return out


def pg_info(pod, ns, op):
    def q(sql):
        c = (f"PGPASSWORD={shlex.quote(op['password'])} psql -h 127.0.0.1 -U {op['user']} -d {op['db']} -tAc "
             f"{shlex.quote(sql)}")
        return K.k("exec", "-n", ns, pod["metadata"]["name"], "-c", pod["spec"]["containers"][0]["name"], "--",
                   "sh", "-c", c)

    rc, o, _ = q("select current_setting('data_directory')")
    ddir = o.strip() if rc == 0 and o.strip() else None
    if ddir is None:   # a non-superuser cannot read data_directory: take PGDATA from the container environment
        rc, o, _ = K.k("exec", "-n", ns, pod["metadata"]["name"], "-c", pod["spec"]["containers"][0]["name"], "--",
                       "sh", "-c", 'echo "${PGDATA:-${POSTGRESQL_DATA_DIR:-}}"')
        ddir = o.strip() or None
    rc, o, _ = q("select schemaname || '.' || relname from pg_stat_user_tables")
    if rc:
        return {"data_directory": ddir, "tables": None}
    rows = {}
    for name in o.split():
        rc, o2, _ = q(f"select count(*) from {name}")
        rows[name] = int(o2.strip()) if rc == 0 and o2.strip().isdigit() else None
    return {"data_directory": ddir, "tables": rows}


def image_exists(image):
    rc, _, _ = K.sh(["docker", "manifest", "inspect", image], timeout=60)
    return rc == 0


def collect(s, ns, d):
    fx = {"ns": ns, "steps": collect_steps(s, ns, d)}
    inv = K.kj("get", KINDS, "-n", ns) or {"items": []}
    fx["inventory"] = [clean(o) for o in inv["items"]
                       if not (o["kind"] == "ConfigMap" and o["metadata"]["name"] == "kube-root-ca.crt")
                       and not (o["kind"] == "Secret" and (o.get("type") or "").startswith("helm.sh/"))]
    pods = (K.kj("get", "pods", "-n", ns) or {"items": []})["items"]
    fx["pods"] = []
    for p in pods:
        e = {"name": p["metadata"]["name"], "labels": p["metadata"].get("labels") or {},
             "phase": (p.get("status") or {}).get("phase"),
             "ready": all(c.get("ready") for c in (p.get("status") or {}).get("containerStatuses") or []),
             "owner": [(o["kind"], o["name"]) for o in p["metadata"].get("ownerReferences") or []],
             "spec": clean({"spec": p["spec"]})["spec"], "emptydir_kb": {}}
        for v in p["spec"].get("volumes") or []:
            if "emptyDir" in v:
                e["emptydir_kb"][v["name"]] = emptydir_usage(p, v["name"])
        for op in s["seed"]:
            sel_k, _, sel_v = op["pod"].partition("=")
            if e["labels"].get(sel_k) == sel_v and e["phase"] == "Running":
                e["redis" if op["op"] == "redis" else "postgres"] = (
                    redis_config(p, ns, op["password"]) if op["op"] == "redis" else pg_info(p, ns, op))
        fx["pods"].append(e)
    pvs = (K.kj("get", "pv") or {"items": []})["items"]
    fx["pvs"] = []
    for pv in pvs:
        ref = pv["spec"].get("claimRef") or {}
        if ref.get("namespace") == ns:
            fx["pvs"].append({"name": pv["metadata"]["name"], "claim": ref.get("name"),
                              "reclaim": pv["spec"].get("persistentVolumeReclaimPolicy"),
                              "storageClass": pv["spec"].get("storageClassName"),
                              "phase": (pv.get("status") or {}).get("phase"), "kb": pv_usage(pv)})
    fx["storageclasses"] = {sc["metadata"]["name"]: {"reclaimPolicy": sc.get("reclaimPolicy"),
                                                     "provisioner": sc.get("provisioner"),
                                                     "volumeBindingMode": sc.get("volumeBindingMode")}
                            for sc in (K.kj("get", "storageclass") or {"items": []})["items"]}
    crbs = (K.kj("get", "clusterrolebinding") or {"items": []})["items"]
    fx["clusterrolebindings"] = [clean(b) for b in crbs
                                 if any(sj.get("namespace") == ns for sj in b.get("subjects") or [])]
    fx["rbac_now"] = {}
    for who, flags in IDENTITIES.items():
        fx["rbac_now"][who] = [f"{v} {r}" for v, r in VERBS
                               if K.k("auth", "can-i", v, r, "-n", ns, *[f.format(ns=ns) for f in flags])[1].strip() == "yes"]
    running = {c["image"] for p in pods for c in p["spec"]["containers"]}
    new_images = set()
    for st in fx["steps"]:
        for o in st["objects"]:
            tpl = ((o.get("desired") or {}).get("spec") or {}).get("template") or {}
            for c in (tpl.get("spec") or {}).get("containers") or []:
                if c.get("image") and c["image"] not in running:
                    new_images.add(c["image"])
    fx["images"] = {im: image_exists(im) for im in sorted(new_images)}
    fx["node_count"] = len((K.kj("get", "nodes") or {"items": []})["items"])
    return fx
