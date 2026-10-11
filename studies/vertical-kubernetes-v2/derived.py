"""Derived facts computed from the raw facts (facts.py) with no model involved. They are shared: guard.py renders them
into the Ekbasis state, and rule2.py (the rich rule) decides from them. Nothing here looks at labels.

  effective(fx)       which objects each command changes, creates or deletes once the dry-run verdicts are applied
                      (a rejected object is not changed; a helm upgrade with a rejected object applies the others but
                      deletes nothing; a kubectl step that fails stops the commands after it).
  before / after      the namespace's objects before and after.
  workloads           per Deployment/StatefulSet: does the pod template change, which pods get replaced or deleted,
                      the minimum number of ready pods the strategy keeps during the rollout.
  services            per Service: what its selector and targetPort meet before and after.
  reach               per workload: can the client namespace / an arbitrary other namespace reach its pods, before and
                      after (NetworkPolicy evaluation).
  rbac_new            grants the change adds for the three identities (evaluation of the Roles/ClusterRoles bound).
  data                per pod holding data: where its data directory lives and what happens to that pod and volume.
"""
from __future__ import annotations

import json
import math
import re

WORKLOADS = ("Deployment", "StatefulSet")
DB_IMAGE = re.compile(r"(^|/)(postgres|postgresql|mysql|mariadb|redis|grafana)[:@]")


# ---------------------------------------------------------------- selectors

def sel_match(sel, labels):
    """Kubernetes label selector (matchLabels + matchExpressions). None selects nothing; {} selects everything."""
    if sel is None:
        return False
    labels = labels or {}
    for k, v in (sel.get("matchLabels") or {}).items():
        if labels.get(k) != v:
            return False
    for e in sel.get("matchExpressions") or []:
        k, op, vals = e.get("key"), e.get("operator"), e.get("values") or []
        if op == "In" and labels.get(k) not in vals:
            return False
        if op == "NotIn" and labels.get(k) in vals:
            return False
        if op == "Exists" and k not in labels:
            return False
        if op == "DoesNotExist" and k in labels:
            return False
    return True


def svc_match(sel, labels):
    return bool(sel) and all((labels or {}).get(k) == v for k, v in sel.items())


# ---------------------------------------------------------------- the effective change

def entries(fx):
    """[(step_index, step_type, entry, applied: bool)] in order."""
    out = []
    stopped = False
    for i, st in enumerate(fx["steps"]):
        bad = bool(st.get("render_error")) or any(e.get("dry_run_error") for e in st["objects"])
        for e in st["objects"]:
            if stopped or st.get("render_error"):
                ok = False
            elif e["action"] == "delete" and st["type"] == "helm upgrade" and bad:
                ok = False             # helm stops before deleting when an update failed
            elif e["action"].startswith("kept"):
                ok = False
            else:
                ok = not e.get("dry_run_error")
            out.append((i, st["type"], e, ok))
        if bad and st["type"].startswith("kubectl"):
            stopped = True
        if st.get("render_error"):
            stopped = True
    return out


def fails(fx):
    return any(st.get("render_error") for st in fx["steps"]) or any(e.get("dry_run_error") for st in fx["steps"]
                                                                     for e in st["objects"])


def objects_before(fx):
    return {(o["kind"], o["metadata"]["name"]): o for o in fx["inventory"]}


def objects_after(fx):
    objs = objects_before(fx)
    for _, _, e, ok in entries(fx):
        if not ok:
            continue
        key = (e["kind"], e["name"])
        if e["action"] == "delete":
            objs.pop(key, None)
        elif e.get("dry") and e["action"] in ("create", "update", "unchanged"):
            objs[key] = e["dry"]
    return objs


def applied(fx):
    return [(e, st) for _, st, e, ok in entries(fx) if ok]


# ---------------------------------------------------------------- workloads

def int_or_pct(v, n, up):
    if isinstance(v, str) and v.endswith("%"):
        x = n * int(v[:-1]) / 100
        return math.ceil(x) if up else math.floor(x)
    return int(v)


def tpl(o):
    return ((o or {}).get("spec") or {}).get("template") or {}


def containers(o):
    return (tpl(o).get("spec") or {}).get("containers") or []


def deploy_min_ready(o):
    sp = o["spec"]
    n = sp.get("replicas", 1)
    st = sp.get("strategy") or {}
    if st.get("type") == "Recreate":
        return 0
    r = st.get("rollingUpdate") or {}
    surge = int_or_pct(r.get("maxSurge", "25%"), n, True)
    unav = int_or_pct(r.get("maxUnavailable", "25%"), n, False)
    if surge == 0 and unav == 0:
        unav = 1
    return max(n - unav, 0)


def pods_of_workload(fx, o):
    sel = (o.get("spec") or {}).get("selector")
    return [p for p in fx["pods"] if sel_match(sel, p["labels"])]


def images_ok(fx, o):
    imgs = [c.get("image") for c in containers(o) + ((tpl(o).get("spec") or {}).get("initContainers") or [])]
    return all(fx["images"].get(i, True) for i in imgs if i)


def workloads(fx):
    """Per workload in the namespace: what the change does to its pods."""
    before, after = objects_before(fx), objects_after(fx)
    out = {}
    for key in set(k for k in before if k[0] in WORKLOADS) | set(k for k in after if k[0] in WORKLOADS):
        b, a = before.get(key), after.get(key)
        kind, name = key
        w = {"kind": kind, "name": name, "exists_before": b is not None, "exists_after": a is not None,
             "pods_now": [p["name"] for p in pods_of_workload(fx, b)] if b else []}
        if b and not a:
            w.update(fate="deleted", pods_replaced=w["pods_now"], min_ready=0)
        elif a and not b:
            w.update(fate="created", pods_replaced=[], min_ready=None)
        else:
            tchg = json.dumps(tpl(b), sort_keys=True) != json.dumps(tpl(a), sort_keys=True)
            nb, na = b["spec"].get("replicas", 1), a["spec"].get("replicas", 1)
            w.update(template_changed=tchg, replicas_before=nb, replicas_after=na, new_images_exist=images_ok(fx, a),
                     readiness_probe_after=all(c.get("readinessProbe") for c in containers(a)))
            replaced, min_ready = [], na
            if kind == "Deployment":
                st = (a["spec"].get("strategy") or {}).get("type", "RollingUpdate")
                w["strategy"] = st
                if tchg:
                    replaced = list(w["pods_now"])
                    min_ready = deploy_min_ready(a)
                    if not w["new_images_exist"] and st != "Recreate":
                        # new pods never become ready: only the pods maxUnavailable allows are removed
                        keep = min(min_ready, len(w["pods_now"]))
                        replaced = w["pods_now"][keep:]
            else:
                us = a["spec"].get("updateStrategy") or {"type": "RollingUpdate"}
                part = (us.get("rollingUpdate") or {}).get("partition") or 0
                w["strategy"] = us.get("type", "RollingUpdate") + (f" partition {part}" if part else "")
                pods = sorted(w["pods_now"], key=lambda n: -int(n.rsplit("-", 1)[-1]) if n.rsplit("-", 1)[-1].isdigit() else 0)
                if na < nb:   # scale down removes the highest ordinals
                    replaced += [p for p in pods if p.rsplit("-", 1)[-1].isdigit() and int(p.rsplit("-", 1)[-1]) >= na]
                if tchg and us.get("type", "RollingUpdate") == "RollingUpdate":
                    upd = [p for p in pods if p not in replaced and p.rsplit("-", 1)[-1].isdigit()
                           and int(p.rsplit("-", 1)[-1]) >= part]
                    if not w["new_images_exist"]:
                        upd = upd[:1]     # the rollout stops at the first pod that never becomes ready
                    replaced += upd
                # StatefulSet pods are deleted before their replacement exists (no surge)
                min_ready = max(min(na, nb) - (1 if replaced else 0), 0) if tchg else na
                if na < nb and not tchg:
                    min_ready = na
            w.update(fate="updated" if (w.get("template_changed") or nb != na) else "unchanged",
                     pods_replaced=sorted(set(replaced)), min_ready=min_ready)
        out[key] = w
    return out


# ---------------------------------------------------------------- services

def svc_backends(o, objs):
    sel = (o.get("spec") or {}).get("selector") or {}
    return [(k, w) for k, w in objs.items() if k[0] in WORKLOADS and svc_match(sel, (tpl(w).get("metadata") or {}).get("labels"))]


def target_ok(port, backends):
    t = port.get("targetPort", port.get("port"))
    cs = [c for _, w in backends for c in containers(w)]
    if isinstance(t, str):
        return any(cp.get("name") == t for c in cs for cp in c.get("ports") or [])
    declared = {cp.get("containerPort") for c in cs for cp in c.get("ports") or []}
    return t in declared or not declared


def services(fx):
    before, after = objects_before(fx), objects_after(fx)
    out = {}
    for key in set(k for k in before if k[0] == "Service") | set(k for k in after if k[0] == "Service"):
        b, a = before.get(key), after.get(key)
        s = {"name": key[1], "exists_before": b is not None, "exists_after": a is not None}
        for tag, o, objs in (("before", b, before), ("after", a, after)):
            if not o:
                continue
            bk = svc_backends(o, objs)
            s[f"backends_{tag}"] = [f"{k[0]} {k[1]}" for k, _ in bk]
            s[f"ports_{tag}"] = sorted(p.get("port") for p in o["spec"].get("ports") or [])
            s[f"type_{tag}"] = o["spec"].get("type", "ClusterIP")
            s[f"targets_ok_{tag}"] = all(target_ok(p, bk) for p in o["spec"].get("ports") or [])
            s[f"node_ports_{tag}"] = s[f"type_{tag}"] in ("NodePort", "LoadBalancer")
        out[key] = s
    return out


# ---------------------------------------------------------------- network policies

def allowed_from(fx, objs, pod_labels, src_ns_labels, src_same_ns=False):
    """Can a pod (labels) receive ingress from a pod with no particular labels in a namespace with src_ns_labels?"""
    pols = [o for k, o in objs.items() if k[0] == "NetworkPolicy"
            and "Ingress" in (o["spec"].get("policyTypes") or ["Ingress"])
            and sel_match(o["spec"].get("podSelector") or {}, pod_labels)]
    if not pols:
        return True
    for p in pols:
        for r in p["spec"].get("ingress") or []:
            frm = r.get("from")
            if not frm:
                return True
            for f in frm:
                if "ipBlock" in f:
                    if f["ipBlock"].get("cidr") == "0.0.0.0/0" and not f["ipBlock"].get("except"):
                        return True
                    continue
                if "namespaceSelector" in f:
                    if sel_match(f["namespaceSelector"], src_ns_labels) and \
                            sel_match(f.get("podSelector") or {}, {}):
                        return True
                elif "podSelector" in f and src_same_ns and sel_match(f["podSelector"], {}):
                    return True
    return False


def reach(fx):
    """Per workload that a Service sends to: reachable from the clients' namespace / from an arbitrary other
    namespace, before and after."""
    before, after = objects_before(fx), objects_after(fx)
    client_labels = (fx.get("namespaces") or {"vk-probe": {"role": "client"}}).get(fx.get("clients_namespace", "vk-probe"), {})
    out = {}
    for tag, objs in (("before", before), ("after", after)):
        for k, w in objs.items():
            if k[0] not in WORKLOADS:
                continue
            lab = (tpl(w).get("metadata") or {}).get("labels") or {}
            r = out.setdefault(k, {})
            r[f"clients_{tag}"] = allowed_from(fx, objs, lab, client_labels)
            r[f"other_ns_{tag}"] = allowed_from(fx, objs, lab, {})
    return out


# ---------------------------------------------------------------- RBAC

def identities(ns):
    return {"the namespace's default ServiceAccount": ("system:serviceaccount:%s:default" % ns,
                                                       {"system:serviceaccounts", f"system:serviceaccounts:{ns}",
                                                        "system:authenticated"}),
            "the default ServiceAccount of another namespace": ("system:serviceaccount:vk-outside:default",
                                                                {"system:serviceaccounts", "system:serviceaccounts:vk-outside",
                                                                 "system:authenticated"}),
            "any authenticated user": ("vk-random-user", {"system:authenticated"})}


VERBS = [("get", "secrets"), ("list", "secrets"), ("create", "pods"), ("create", "pods/exec")]


def rule_allows(rules, verb, res):
    for r in rules or []:
        if not ({"", "*"} & set(r.get("apiGroups") or [])):
            continue
        if r.get("resourceNames"):
            continue
        if (verb in (r.get("verbs") or []) or "*" in (r.get("verbs") or [])) and \
                (res in (r.get("resources") or []) or "*" in (r.get("resources") or [])):
            return True
    return False


def subject_is(s, user, groups, ns):
    if s["kind"] == "ServiceAccount":
        return user == f"system:serviceaccount:{s.get('namespace', ns)}:{s['name']}"
    if s["kind"] == "User":
        return s["name"] == user
    if s["kind"] == "Group":
        return s["name"] in groups
    return False


def rbac_new(fx):
    """Grants of the bindings the change creates or updates, and of the bindings that use a Role the change updates;
    returns {identity: [verb resource, ...]} for permissions the identity does not have now."""
    ns = fx["ns"]
    after = objects_after(fx)
    roles = {("Role", k[1]): o for k, o in after.items() if k[0] == "Role"}
    croles = {n: {"rules": v["rules"]} for n, v in (fx.get("clusterroles") or {}).items()}
    changed_bindings, changed_roles = [], set()
    for e, _ in applied(fx):
        if e["action"] in ("create", "update") and e.get("dry"):
            if e["kind"] in ("RoleBinding", "ClusterRoleBinding"):
                changed_bindings.append(e["dry"])
            elif e["kind"] == "Role":
                changed_roles.add(("Role", e["name"]))
            elif e["kind"] == "ClusterRole":
                croles[e["name"]] = {"rules": e["dry"].get("rules") or []}
                changed_roles.add(("ClusterRole", e["name"]))
    for k, o in after.items():
        if k[0] == "RoleBinding" and (o["roleRef"]["kind"], o["roleRef"]["name"]) in changed_roles:
            changed_bindings.append(o)
    out = {}
    for who, (user, groups) in identities(ns).items():
        now = set(fx["rbac_now"].get(who) or [])
        new = []
        for b in changed_bindings:
            if not any(subject_is(s, user, groups, ns) for s in b.get("subjects") or []):
                continue
            rr = b["roleRef"]
            rules = (roles.get(("Role", rr["name"])) or {}).get("rules") if rr["kind"] == "Role" else \
                (croles.get(rr["name"]) or {}).get("rules")
            for verb, res in VERBS:
                v = f"{verb} {res}"
                if v not in now and v not in new and rule_allows(rules, verb, res):
                    new.append(v)
        if new:
            out[who] = new
    return out


# ---------------------------------------------------------------- data

def data_dir_of(p):
    for kind in ("postgres", "mysql", "redis", "grafana"):
        if p.get(kind):
            d = p[kind].get("data_directory") or p[kind].get("dir")
            return kind, d
    return None, None


def volume_of(p, path):
    vols = {v["name"]: v for v in p["spec"].get("volumes") or []}
    mounts = [(m["mountPath"], vols.get(m["name"], {"name": m["name"]}), m["name"])
              for c in p["spec"]["containers"] for m in c.get("volumeMounts") or []]
    best = max((m for m in mounts if path and (path == m[0] or path.startswith(m[0].rstrip("/") + "/"))),
               key=lambda m: len(m[0]), default=None)
    if best is None:
        return {"type": "container filesystem"}
    v = best[1]
    if "persistentVolumeClaim" in v:
        return {"type": "pvc", "claim": v["persistentVolumeClaim"]["claimName"]}
    if "emptyDir" in v:
        return {"type": "emptyDir"}
    if len(v) == 1:   # no volume of that name in the pod: a StatefulSet volumeClaimTemplate
        return {"type": "pvc", "claim": f"{best[2]}-{p['name']}"}
    return {"type": next(iter(set(v) - {"name"}), "volume")}


def pvc_fates(fx):
    """PVCs the change deletes (directly, by helm, or by a StatefulSet retention policy), with their reclaimPolicy."""
    rec = {p["claim"]: p["reclaim"] for p in fx["pvs"]}
    sc = fx["storageclasses"]
    inv = {o["metadata"]["name"]: o for o in fx["inventory"] if o["kind"] == "PersistentVolumeClaim"}

    def reclaim(n):
        if n in rec:
            return rec[n]
        o = inv.get(n) or {}
        return (sc.get((o.get("spec") or {}).get("storageClassName") or "standard") or {}).get("reclaimPolicy")

    out = {}
    for e, _ in applied(fx):
        if e["kind"] == "PersistentVolumeClaim" and e["action"] == "delete":
            out[e["name"]] = reclaim(e["name"])
    before, after = objects_before(fx), objects_after(fx)
    for k, o in before.items():
        if k[0] != "StatefulSet":
            continue
        rp = o["spec"].get("persistentVolumeClaimRetentionPolicy") or {}
        a = after.get(k)
        nb = o["spec"].get("replicas", 1)
        na = a["spec"].get("replicas", 1) if a else 0
        gone = range(na, nb) if a else range(nb)
        policy = rp.get("whenScaled") if a else rp.get("whenDeleted")
        if policy == "Delete":
            for t in o["spec"].get("volumeClaimTemplates") or []:
                for i in gone:
                    n = f"{t['metadata']['name']}-{k[1]}-{i}"
                    out[n] = reclaim(n)
    return out


def data(fx):
    """Per pod holding a database/cache/app data: where the data directory lives and what happens to it."""
    ws = workloads(fx)
    replaced = {p for w in ws.values() for p in w.get("pods_replaced", [])}
    deleted_pods = {e["name"] for e, _ in applied(fx) if e["kind"] == "Pod" and e["action"] == "delete"}
    pf = pvc_fates(fx)
    out = []
    for p in fx["pods"]:
        kind, d = data_dir_of(p)
        if not kind:
            continue
        vol = volume_of(p, d)
        r = {"pod": p["name"], "kind": kind, "data_directory": d, "volume": vol,
             "pod_replaced_or_deleted": p["name"] in replaced or p["name"] in deleted_pods}
        if kind == "redis":
            rd = p["redis"]
            r["redis_persists"] = bool((rd.get("save") or "").strip()) or rd.get("appendonly") == "yes"
        if vol.get("type") == "pvc":
            r["pvc_deleted"] = vol["claim"] in pf
            r["pvc_reclaim"] = pf.get(vol["claim"])
        out.append(r)
    return out
