"""WS-K8S Phase 1: the state the guard reads (Phase 0's summarizer + object annotations) and the facts text the simulated
user reads (one line per object, the same in every condition)."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "probe"))
import kube  # noqa: E402
import observe  # noqa: E402

SKIP_ANN = ("kubectl.kubernetes.io/last-applied-configuration", "deployment.kubernetes.io/", "pv.kubernetes.io/",
            "volume.kubernetes.io/", "volume.beta.kubernetes.io/", "local.path.provisioner/")
KINDS = {"deployments": "deployments.apps", "statefulSets": "statefulsets.apps", "daemonSets": "daemonsets.apps",
         "services": "services", "configMaps": "configmaps", "persistentVolumeClaims": "persistentvolumeclaims"}


def _ann(o):
    return {k: v for k, v in (o["metadata"].get("annotations") or {}).items() if not k.startswith(SKIP_ANN)}


def summarize(namespaces, files=None):
    s = observe.summarize(namespaces, files)
    for nsd in s["namespaces"]:
        for key, kind in KINDS.items():
            if key not in nsd:
                continue
            ann = {o["metadata"]["name"]: _ann(o) for o in kube.items(kind, nsd["name"])}
            for e in nsd[key]:
                if ann.get(e["name"]):
                    e["annotations"] = ann[e["name"]]
    return s


def _kv(d):
    return ", ".join(f"{k}={v}" for k, v in (d or {}).items()) or "none"


def _workload_line(kind, ns, w):
    parts = []
    if "replicas" in w:
        parts.append(f"replicas {w['replicas']} (ready {w.get('readyReplicas', 0)})")
    if "desiredNumberScheduled" in w:
        parts.append(f"pods wanted {w.get('desiredNumberScheduled')} (ready {w.get('numberReady')})")
    parts.append(f"selector {_kv(w.get('selector'))}")
    parts.append(f"pod labels {_kv(w.get('pod_labels'))}")
    if w.get("strategy"):
        parts.append(f"strategy {w['strategy']}")
    if "persistentVolumeClaimRetentionPolicy" in w:
        r = w.get("persistentVolumeClaimRetentionPolicy") or {}
        parts.append(f"retention whenDeleted={r.get('whenDeleted', 'Retain')} whenScaled={r.get('whenScaled', 'Retain')}")
    for t in w.get("volumeClaimTemplates") or []:
        parts.append(f"claim template {t['name']} {t['storage']} class {t.get('storageClassName')}")
    if w.get("serviceName"):
        parts.append(f"serviceName {w['serviceName']}")
    if w.get("nodeSelector"):
        parts.append(f"nodeSelector {_kv(w['nodeSelector'])}")
    if w.get("tolerations"):
        parts.append("tolerations " + "; ".join(f"{t.get('key')} {t.get('operator', 'Equal')} {t.get('effect', '')}".strip()
                                                 for t in w["tolerations"]))
    for c in w.get("containers") or []:
        if c.get("env"):
            parts.append(f"env {_kv(c['env'])}")
        for e in c.get("envFrom") or []:
            src = "configMap " + e["configMap"] if "configMap" in e else "secret " + e.get("secret", "?")
            parts.append(f"envFrom {src} (optional {str(e.get('optional')).lower()})")
    for v in w.get("volumes") or []:
        if "configMap" in v:
            parts.append(f"volume {v['name']} from configMap {v['configMap']} (optional {str(v.get('optional')).lower()})")
        elif "pvc" in v:
            parts.append(f"volume {v['name']} from claim {v['pvc']}")
    pods = ", ".join(f"{p['name']} on {p['node']} ({'ready' if p['ready'] else p['status']})" for p in w.get("pods") or [])
    parts.append(f"pods: {pods or 'none'}")
    if w.get("labels"):
        parts.append(f"labels {_kv(w['labels'])}")
    if w.get("annotations"):
        parts.append("annotations " + "; ".join(f'{k}="{v}"' for k, v in w["annotations"].items()))
    parts.append(f"applied_with_kubectl_apply {str(w.get('applied_with_kubectl_apply')).lower()}")
    return f"{kind} {ns}/{w['name']}: " + ", ".join(parts)


def facts_text(s):
    """The facts the simulated user reads: one line per object."""
    out = []
    for n in s.get("nodes", []):
        t = "; ".join(f"{x.get('key')}={x.get('value', '')}:{x.get('effect')}" for x in n.get("taints") or []) or "none"
        out.append(f"Node {n['name']} ({n['role']}): taints {t}" + (", unschedulable" if n.get("unschedulable") else ""))
    for nsd in s.get("namespaces", []):
        ns = nsd["name"]
        out.append(f"Namespace {ns}: labels {_kv({k: v for k, v in nsd.get('labels', {}).items() if not k.startswith('kubernetes.io/')})}")
        for w in nsd.get("deployments", []):
            out.append(_workload_line("Deployment", ns, w))
        for w in nsd.get("statefulSets", []):
            out.append(_workload_line("StatefulSet", ns, w))
        for w in nsd.get("daemonSets", []):
            out.append(_workload_line("DaemonSet", ns, w))
        for r in nsd.get("replicaSets", []):
            out.append(f"ReplicaSet {ns}/{r['name']}: owner {r.get('owner') or 'none'}, replicas {r.get('replicas')} (ready {r.get('readyReplicas')})")
        for p in nsd.get("otherPods", []):
            out.append(f"Pod {ns}/{p['name']}: owner {p.get('owner') or 'none'}, on {p.get('node')}, {'ready' if p.get('ready') else p.get('status')}, labels {_kv(p.get('labels'))}")
        for v in nsd.get("services", []):
            line = f"Service {ns}/{v['name']}: selector {_kv(v.get('selector'))}, ready endpoints {v.get('readyEndpoints')}"
            if v.get("labels"):
                line += f", labels {_kv(v['labels'])}"
            if v.get("annotations"):
                line += ", annotations " + "; ".join(f'{k}="{x}"' for k, x in v["annotations"].items())
            out.append(line + f", applied_with_kubectl_apply {str(v.get('applied_with_kubectl_apply')).lower()}")
        for c in nsd.get("configMaps", []):
            line = f"ConfigMap {ns}/{c['name']}: keys {', '.join(c.get('keys') or []) or 'none'}"
            if c.get("labels"):
                line += f", labels {_kv(c['labels'])}"
            if c.get("annotations"):
                line += ", annotations " + "; ".join(f'{k}="{x}"' for k, x in c["annotations"].items())
            out.append(line)
        for c in nsd.get("persistentVolumeClaims", []):
            line = (f"PersistentVolumeClaim {ns}/{c['name']}: {c.get('status')} to {c.get('volume')}, class {c.get('storageClassName')}, "
                    f"size {c.get('storage')}, used by {', '.join(c.get('usedByPods') or []) or 'no pod'}")
            if c.get("owner"):
                line += f", owner {c['owner']}"
            if c.get("labels"):
                line += f", labels {_kv(c['labels'])}"
            if c.get("annotations"):
                line += ", annotations " + "; ".join(f'{k}="{x}"' for k, x in c["annotations"].items())
            out.append(line)
        for q in nsd.get("resourceQuotas", []):
            out.append(f"ResourceQuota {ns}/{q['name']}: hard {_kv(q.get('hard'))}, used {_kv(q.get('used'))}")
    for pv in s.get("persistentVolumes", []):
        out.append(f"PersistentVolume {pv['name']}: claim {pv['claim']}, reclaimPolicy {pv['reclaimPolicy']}, status {pv['status']}, "
                   f"{'holds data (' + pv['data'] + ')' if pv.get('data') and pv['data'] != 'empty' else 'empty'}")
    for path, txt in (s.get("files") or {}).items():
        out.append(f"File {path}:\n{txt.rstrip()}")
    return "\n".join(out)
