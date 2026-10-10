"""WS-K8S Phase 0: what the forecasters see (summary) and what the truth is computed from (snapshot).

summarize(): the compact state summary of SPEC_probe.md §5 — generic, read from the live cluster, the same code for every
scenario; no UIDs, cluster IPs or timestamps.
snapshot(): the raw facts for the truth (§3): pods, services' ready endpoints, workloads, objects by UID, volumes.
"""
from __future__ import annotations

import json

import kube

LAST_APPLIED = "kubectl.kubernetes.io/last-applied-configuration"
SKIP_CM = {"kube-root-ca.crt"}
TRUTH_KINDS = ["deployments.apps", "replicasets.apps", "statefulsets.apps", "daemonsets.apps", "jobs.batch", "services",
               "configmaps", "secrets", "serviceaccounts", "resourcequotas", "persistentvolumeclaims"]


def _labels(o):
    return dict(o["metadata"].get("labels") or {})


def _applied(o):
    return LAST_APPLIED in (o["metadata"].get("annotations") or {})


def _owner(o):
    refs = o["metadata"].get("ownerReferences") or []
    return f"{refs[0]['kind']}/{refs[0]['name']}" if refs else None


def _pod_ready(p):
    return any(c.get("type") == "Ready" and c.get("status") == "True" for c in (p.get("status", {}).get("conditions") or []))


def _pod_state(p):
    st = p.get("status", {})
    if p["metadata"].get("deletionTimestamp"):
        return "Terminating"
    for cs in st.get("containerStatuses") or []:
        w = (cs.get("state") or {}).get("waiting")
        if w and w.get("reason"):
            return w["reason"]
    return st.get("phase")


def _containers(spec):
    out = []
    for c in spec.get("containers", []):
        d = {"name": c["name"], "image": c.get("image")}
        if c.get("env"):
            d["env"] = {e["name"]: e.get("value") for e in c["env"]}
        if c.get("envFrom"):
            d["envFrom"] = [({"configMap": e["configMapRef"]["name"], "optional": bool(e["configMapRef"].get("optional"))}
                             if "configMapRef" in e else
                             {"secret": e["secretRef"]["name"], "optional": bool(e["secretRef"].get("optional"))})
                            for e in c["envFrom"]]
        req = (c.get("resources") or {}).get("requests")
        if req:
            d["requests"] = req
        if c.get("volumeMounts"):
            d["mounts"] = {m["name"]: m["mountPath"] for m in c["volumeMounts"]}
        out.append(d)
    return out


def _volumes(spec):
    out = []
    for v in spec.get("volumes") or []:
        if "persistentVolumeClaim" in v:
            out.append({"name": v["name"], "pvc": v["persistentVolumeClaim"]["claimName"]})
        elif "configMap" in v:
            out.append({"name": v["name"], "configMap": v["configMap"]["name"], "optional": bool(v["configMap"].get("optional"))})
        elif "secret" in v:
            out.append({"name": v["name"], "secret": v["secret"]["secretName"], "optional": bool(v["secret"].get("optional"))})
        elif "emptyDir" in v:
            out.append({"name": v["name"], "emptyDir": True})
        else:
            out.append({"name": v["name"], "other": [k for k in v if k != "name"]})
    return out


def _template(tpl):
    spec = tpl.get("spec", {})
    d = {"pod_labels": dict((tpl.get("metadata") or {}).get("labels") or {}), "containers": _containers(spec)}
    vols = _volumes(spec)
    if vols:
        d["volumes"] = vols
    if spec.get("nodeSelector"):
        d["nodeSelector"] = spec["nodeSelector"]
    if spec.get("tolerations"):
        d["tolerations"] = spec["tolerations"]
    if spec.get("affinity"):
        d["affinity"] = spec["affinity"]
    return d


def _pods_of(pods, owner_names):
    return [{"name": p["metadata"]["name"], "node": p["spec"].get("nodeName"), "status": _pod_state(p), "ready": _pod_ready(p)}
            for p in pods if _owner(p) in owner_names]


def _ready_endpoints(slices, svc):
    n = 0
    for s in slices:
        if (s["metadata"].get("labels") or {}).get("kubernetes.io/service-name") != svc:
            continue
        for e in s.get("endpoints") or []:
            if (e.get("conditions") or {}).get("ready"):
                n += 1
    return n


def summarize(namespaces, files=None):
    """The forecasters' state (SPEC §5). Call before the command."""
    nodes = []
    for n in kube.items("nodes"):
        roles = [k.split("/", 1)[1] for k in _labels(n) if k.startswith("node-role.kubernetes.io/")]
        d = {"name": n["metadata"]["name"], "role": roles[0] if roles else "worker",
             "taints": [{k: t[k] for k in ("key", "value", "effect") if k in t} for t in n["spec"].get("taints") or []]}
        if n["spec"].get("unschedulable"):
            d["unschedulable"] = True
        nodes.append(d)
    scs = [{"name": s["metadata"]["name"], "provisioner": s["provisioner"], "reclaimPolicy": s.get("reclaimPolicy", "Delete"),
            "default": (s["metadata"].get("annotations") or {}).get("storageclass.kubernetes.io/is-default-class") == "true"}
           for s in kube.items("storageclasses")]
    out = {"nodes": nodes, "storageClasses": scs, "namespaces": [], "persistentVolumes": []}
    claim_keys = set()
    for ns in namespaces:
        nso = kube.kj("get", "namespace", ns)
        pods = kube.items("pods", ns)
        rss = kube.items("replicasets.apps", ns)
        slices = kube.items("endpointslices.discovery.k8s.io", ns)
        d = {"name": ns, "labels": _labels(nso), "applied_with_kubectl_apply": _applied(nso)}
        deps = []
        for o in kube.items("deployments.apps", ns):
            nm = o["metadata"]["name"]
            my_rs = [r["metadata"]["name"] for r in rss if _owner(r) == f"Deployment/{nm}"]
            strat = o["spec"].get("strategy", {})
            st = strat.get("type")
            if st == "RollingUpdate" and strat.get("rollingUpdate"):
                st += f" (maxSurge {strat['rollingUpdate'].get('maxSurge')}, maxUnavailable {strat['rollingUpdate'].get('maxUnavailable')})"
            deps.append({"name": nm, "labels": _labels(o), "applied_with_kubectl_apply": _applied(o),
                         "replicas": o["spec"].get("replicas"), "readyReplicas": o.get("status", {}).get("readyReplicas", 0),
                         "selector": o["spec"]["selector"].get("matchLabels"), "strategy": st,
                         **_template(o["spec"]["template"]),
                         "pods": _pods_of(pods, {f"ReplicaSet/{r}" for r in my_rs})})
        if deps:
            d["deployments"] = deps
        rs_list = [{"name": r["metadata"]["name"], "owner": _owner(r), "replicas": r["spec"].get("replicas"),
                    "readyReplicas": r.get("status", {}).get("readyReplicas", 0)} for r in rss]
        if rs_list:
            d["replicaSets"] = rs_list
        stss = []
        for o in kube.items("statefulsets.apps", ns):
            nm = o["metadata"]["name"]
            stss.append({"name": nm, "labels": _labels(o), "applied_with_kubectl_apply": _applied(o),
                         "replicas": o["spec"].get("replicas"), "readyReplicas": o.get("status", {}).get("readyReplicas", 0),
                         "serviceName": o["spec"].get("serviceName"), "selector": o["spec"]["selector"].get("matchLabels"),
                         "podManagementPolicy": o["spec"].get("podManagementPolicy"),
                         "updateStrategy": (o["spec"].get("updateStrategy") or {}).get("type"),
                         "persistentVolumeClaimRetentionPolicy": o["spec"].get("persistentVolumeClaimRetentionPolicy"),
                         "volumeClaimTemplates": [{"name": t["metadata"]["name"],
                                                   "storageClassName": t["spec"].get("storageClassName"),
                                                   "storage": t["spec"]["resources"]["requests"]["storage"]}
                                                  for t in o["spec"].get("volumeClaimTemplates") or []],
                         **_template(o["spec"]["template"]),
                         "pods": _pods_of(pods, {f"StatefulSet/{nm}"})})
        if stss:
            d["statefulSets"] = stss
        dss = []
        for o in kube.items("daemonsets.apps", ns):
            nm = o["metadata"]["name"]
            dss.append({"name": nm, "labels": _labels(o), "applied_with_kubectl_apply": _applied(o),
                        "desiredNumberScheduled": o.get("status", {}).get("desiredNumberScheduled"),
                        "numberReady": o.get("status", {}).get("numberReady"),
                        "selector": o["spec"]["selector"].get("matchLabels"), **_template(o["spec"]["template"]),
                        "pods": _pods_of(pods, {f"DaemonSet/{nm}"})})
        if dss:
            d["daemonSets"] = dss
        owned = {f"ReplicaSet/{r['metadata']['name']}" for r in rss} | {f"StatefulSet/{s['name']}" for s in stss} | \
            {f"DaemonSet/{x['name']}" for x in dss}
        bare = [p for p in pods if _owner(p) not in owned]
        if bare:
            d["otherPods"] = [{"name": p["metadata"]["name"], "owner": _owner(p), "node": p["spec"].get("nodeName"),
                               "status": _pod_state(p), "ready": _pod_ready(p), "labels": _labels(p)} for p in bare]
        svcs = [{"name": o["metadata"]["name"], "labels": _labels(o), "applied_with_kubectl_apply": _applied(o),
                 "type": o["spec"].get("type"), "selector": o["spec"].get("selector"),
                 "readyEndpoints": _ready_endpoints(slices, o["metadata"]["name"])}
                for o in kube.items("services", ns)]
        if svcs:
            d["services"] = svcs
        cms = [{"name": o["metadata"]["name"], "labels": _labels(o), "applied_with_kubectl_apply": _applied(o),
                "keys": sorted((o.get("data") or {}).keys())}
               for o in kube.items("configmaps", ns) if o["metadata"]["name"] not in SKIP_CM]
        if cms:
            d["configMaps"] = cms
        claims = []
        for o in kube.items("persistentvolumeclaims", ns):
            nm = o["metadata"]["name"]
            users = [p["metadata"]["name"] for p in pods
                     if any((v.get("persistentVolumeClaim") or {}).get("claimName") == nm for v in p["spec"].get("volumes") or [])]
            c = {"name": nm, "labels": _labels(o), "applied_with_kubectl_apply": _applied(o),
                 "status": o.get("status", {}).get("phase"), "volume": o["spec"].get("volumeName"),
                 "storageClassName": o["spec"].get("storageClassName"),
                 "storage": o["spec"]["resources"]["requests"]["storage"], "usedByPods": users}
            if _owner(o):
                c["owner"] = _owner(o)
            claims.append(c)
            claim_keys.add((ns, nm))
        if claims:
            d["persistentVolumeClaims"] = claims
        qs = [{"name": o["metadata"]["name"], "hard": o["spec"].get("hard"), "used": o.get("status", {}).get("used")}
              for o in kube.items("resourcequotas", ns)]
        if qs:
            d["resourceQuotas"] = qs
        hpas = [{"name": o["metadata"]["name"], "target": o["spec"].get("scaleTargetRef", {}).get("name"),
                 "minReplicas": o["spec"].get("minReplicas"), "maxReplicas": o["spec"].get("maxReplicas")}
                for o in kube.items("horizontalpodautoscalers.autoscaling", ns)]
        if hpas:
            d["horizontalPodAutoscalers"] = hpas
        out["namespaces"].append(d)
    for pv in kube.items("persistentvolumes"):
        ref = pv["spec"].get("claimRef") or {}
        if (ref.get("namespace"), ref.get("name")) not in claim_keys:
            continue
        node, path = kube.pv_location(pv)
        b = kube.payload_bytes(node, path)
        out["persistentVolumes"].append({
            "name": pv["metadata"]["name"], "claim": f"{ref.get('namespace')}/{ref.get('name')}",
            "reclaimPolicy": pv["spec"].get("persistentVolumeReclaimPolicy"), "status": pv.get("status", {}).get("phase"),
            "storageClassName": pv["spec"].get("storageClassName"), "capacity": pv["spec"].get("capacity", {}).get("storage"),
            "node": node, "data": f"payload.txt, {b} bytes (written by the app)" if b is not None else "empty"})
    if files:
        out["files"] = dict(files)
    return out


# --------------------------------------------------------------------------------------------- truth snapshot
def snapshot(namespaces, pv_names=()):
    """Raw facts of the scenario namespaces (+ the given volumes and every volume claimed from them)."""
    snap = {"namespaces": {}, "pods": [], "services": [], "workloads": [], "objects": [], "pvs": []}
    claim_keys = set()
    for ns in namespaces:
        p = kube.kc("get", "namespace", ns, "-o", "json", check=False)
        if p.returncode != 0:
            continue
        nso = json.loads(p.stdout)
        snap["namespaces"][ns] = {"uid": nso["metadata"]["uid"], "phase": nso.get("status", {}).get("phase")}
        for po in kube.items("pods", ns):
            snap["pods"].append({"ns": ns, "name": po["metadata"]["name"], "uid": po["metadata"]["uid"],
                                 "phase": po.get("status", {}).get("phase"), "state": _pod_state(po), "ready": _pod_ready(po),
                                 "deleting": bool(po["metadata"].get("deletionTimestamp")), "node": po["spec"].get("nodeName"),
                                 "owner": _owner(po)})
        slices = kube.items("endpointslices.discovery.k8s.io", ns)
        for kind in TRUTH_KINDS:
            for o in kube.items(kind, ns):
                k = kind.split(".")[0]
                snap["objects"].append({"kind": k, "ns": ns, "name": o["metadata"]["name"], "uid": o["metadata"]["uid"],
                                        "deleting": bool(o["metadata"].get("deletionTimestamp"))})
                if k == "services":
                    snap["services"].append({"ns": ns, "name": o["metadata"]["name"], "uid": o["metadata"]["uid"],
                                             "ready": _ready_endpoints(slices, o["metadata"]["name"])})
                if k in ("deployments", "statefulsets"):
                    snap["workloads"].append({"kind": k, "ns": ns, "name": o["metadata"]["name"], "uid": o["metadata"]["uid"],
                                              "replicas": o["spec"].get("replicas"),
                                              "ready": o.get("status", {}).get("readyReplicas", 0) or 0,
                                              "selector": o["spec"]["selector"].get("matchLabels")})
                if k == "persistentvolumeclaims":
                    claim_keys.add((ns, o["metadata"]["name"]))
    for pv in kube.items("persistentvolumes"):
        ref = pv["spec"].get("claimRef") or {}
        if pv["metadata"]["name"] in pv_names or ref.get("namespace") in namespaces or (ref.get("namespace"), ref.get("name")) in claim_keys:
            node, path = kube.pv_location(pv)
            snap["pvs"].append({"name": pv["metadata"]["name"], "uid": pv["metadata"]["uid"],
                                "claim": f"{ref.get('namespace')}/{ref.get('name')}", "phase": pv.get("status", {}).get("phase"),
                                "reclaim": pv["spec"].get("persistentVolumeReclaimPolicy"), "node": node, "path": path,
                                "payload": kube.payload_bytes(node, path)})
    return snap


def signature(namespaces):
    """What must stop changing before the 'after' snapshot (SPEC §3)."""
    sig = []
    for ns in namespaces:
        p = kube.kc("get", "namespace", ns, "-o", "jsonpath={.status.phase}", check=False)
        sig.append(("ns", ns, p.stdout.strip() if p.returncode == 0 else "absent"))
        for po in kube.items("pods", ns):
            sig.append(("pod", ns, po["metadata"]["name"], _pod_state(po), _pod_ready(po)))
        for c in kube.items("persistentvolumeclaims", ns):
            sig.append(("pvc", ns, c["metadata"]["name"], c.get("status", {}).get("phase"),
                        bool(c["metadata"].get("deletionTimestamp"))))
    for pv in kube.items("persistentvolumes"):
        ref = pv["spec"].get("claimRef") or {}
        if ref.get("namespace") in namespaces:
            sig.append(("pv", pv["metadata"]["name"], pv.get("status", {}).get("phase")))
    return sorted(map(str, sig))
