"""R2, the rich rule of the v2 study. Written from the Kubernetes and Helm documentation, in good faith, BEFORE any test
label and any Ekbasis call, and frozen by hash. It reads exactly the facts the Ekbasis state is built from (facts.py)
and the same derived facts (derived.py), and decides lost / down / exposed (and fails, secondary).

down     (a Service that has ready endpoints now)
  - the Service is deleted, loses a port its clients use, ends up selecting no workload, or its targetPort no longer
    names a port of its pods;
  - every workload behind it is deleted, or one of them drops to 0 ready pods during its rollout: Deployment Recreate;
    RollingUpdate whose replicas - maxUnavailable is 0; a StatefulSet whose only pod is replaced (it is deleted before
    the new one is created);
  - a Deployment rolls out pods with no readiness probe (ready as soon as the container starts) whose process is slow
    to listen: a database/cache/grafana image, or a command that sleeps;
  - the clients' namespace can reach the pods now and cannot afterwards (NetworkPolicy);
  - the database the clients query loses its data (the table is gone).
lost
  - a pod holding data on an emptyDir or in its container filesystem is replaced or deleted (redis included);
  - redis on a PVC with neither save points nor appendonly, and its pod is replaced or deleted;
  - the PVC holding the data is deleted (by kubectl, helm, or a StatefulSet retention policy) with reclaimPolicy
    Delete and its pod is deleted or replaced too (otherwise PVC protection keeps it).
exposed
  - a Service becomes NodePort/LoadBalancer (new or changed) on a port no Service exposed outside before;
  - a hostPort or hostNetwork appears in a pod template that is rolled out;
  - an arbitrary other namespace can reach a workload's pods afterwards and could not before (NetworkPolicy);
  - authentication switched off where the image applies it at every start (redis --requirepass removed, bitnami
    ALLOW_EMPTY_PASSWORD=yes, bitnami helm value auth.enabled false), or where it applies it only to a new data
    directory (POSTGRES_HOST_AUTH_METHOD=trust, MYSQL_ALLOW_EMPTY_PASSWORD) and the data directory is new;
  - a binding/role change grants one of the three identities get/list secrets, create pods or pods/exec.
fails    any dry-run rejection or render error.
"""
from __future__ import annotations

import derived as D

SLOW = D.DB_IMAGE


def _env(c):
    return {e["name"]: e.get("value") for e in c.get("env") or []}


def rule2(fx) -> dict:
    out = {"lost": False, "down": False, "exposed": False, "fails": D.fails(fx), "why": []}

    def flag(k, why):
        out[k] = True
        out["why"].append(f"{k}: {why}")

    before, after = D.objects_before(fx), D.objects_after(fx)
    ws = D.workloads(fx)
    svcs = D.services(fx)
    reach = D.reach(fx)
    dat = D.data(fx)

    # ---------------- lost
    for r in dat:
        v = r["volume"]
        if not r["pod_replaced_or_deleted"]:
            continue
        if v["type"] in ("emptyDir", "container filesystem"):
            flag("lost", f"{r['pod']} keeps its {r['kind']} data on {v['type']} and is replaced/deleted")
        elif v["type"] == "pvc":
            if r["kind"] == "redis" and not r.get("redis_persists", True):
                flag("lost", f"{r['pod']} redis writes nothing to its PVC and is replaced/deleted")
            if r.get("pvc_deleted") and r.get("pvc_reclaim") == "Delete":
                flag("lost", f"PVC {v['claim']} (reclaim Delete) is deleted together with its pod")
    db_lost = out["lost"] and any(r["kind"] in ("postgres", "mysql") and r["pod_replaced_or_deleted"] for r in dat)

    # ---------------- down
    for key, s in svcs.items():
        if not s["exists_before"] or not s.get("backends_before"):
            continue
        if not s["exists_after"]:
            flag("down", f"Service {s['name']} is deleted")
            continue
        if set(s["ports_before"]) - set(s["ports_after"]):
            flag("down", f"Service {s['name']} drops port(s) {sorted(set(s['ports_before']) - set(s['ports_after']))}")
        if not s.get("backends_after"):
            flag("down", f"Service {s['name']} selects no workload afterwards")
            continue
        if s.get("targets_ok_before") and not s.get("targets_ok_after"):
            flag("down", f"Service {s['name']} targetPort matches no port of its pods afterwards")
        back = [ws.get(tuple(b.split(" ", 1))) for b in s["backends_after"]]
        back_before = [ws.get(tuple(b.split(" ", 1))) for b in s["backends_before"]]
        gone = [w for w in back_before if w and w["fate"] == "deleted"]
        if gone and len(gone) == len(back_before) and not any(w and w["fate"] == "created" for w in back):
            flag("down", f"every workload behind Service {s['name']} is deleted")
        for w in back:
            if not w or w["fate"] not in ("updated",):
                continue
            if w.get("pods_replaced") and w.get("min_ready") == 0:
                flag("down", f"{w['kind']} {w['name']} keeps 0 ready pods during its rollout ({w.get('strategy')})")
            if w["kind"] == "Deployment" and w.get("template_changed") and not w.get("readiness_probe_after") \
                    and w.get("new_images_exist"):
                a = after[(w["kind"], w["name"])]
                slow = any(SLOW.search(c.get("image") or "") or "sleep" in " ".join((c.get("command") or []) +
                                                                                   (c.get("args") or []))
                           for c in D.containers(a))
                if slow:
                    flag("down", f"Deployment {w['name']} rolls out pods with no readiness probe that start slowly")
    for k, r in reach.items():
        if r.get("clients_before") and r.get("clients_after") is False:
            if any(s["exists_after"] and f"{k[0]} {k[1]}" in (s.get("backends_after") or []) for s in svcs.values()):
                flag("down", f"{k[0]} {k[1]} no longer accepts connections from the clients' namespace")
    if db_lost:
        flag("down", "the database the clients query loses its data")

    # ---------------- exposed
    ext_before = {p for s in svcs.values() if s.get("node_ports_before") for p in s.get("ports_before", [])}
    for s in svcs.values():
        if s.get("node_ports_after") and not s.get("node_ports_before"):
            new = set(s.get("ports_after", [])) - ext_before
            if new:
                flag("exposed", f"Service {s['name']} becomes {s['type_after']} on port(s) {sorted(new)}")
    for key, w in ws.items():
        a, b = after.get(key), before.get(key)
        if not a:
            continue
        rolled = w["fate"] == "created" or w.get("template_changed")
        if not rolled:
            continue
        hp = lambda o: {p.get("hostPort") for c in D.containers(o) for p in c.get("ports") or [] if p.get("hostPort")}
        if hp(a) - (hp(b) if b else set()):
            flag("exposed", f"{key[0]} {key[1]} adds hostPort(s) {sorted(hp(a) - (hp(b) if b else set()))}")
        if (D.tpl(a).get("spec") or {}).get("hostNetwork") and not (D.tpl(b).get("spec") or {}).get("hostNetwork"):
            flag("exposed", f"{key[0]} {key[1]} switches to hostNetwork")
        old_c = {c["name"]: c for c in D.containers(b)} if b else {}
        for c in D.containers(a):
            oc = old_c.get(c["name"], {})
            argv = lambda x: " ".join((x.get("command") or []) + (x.get("args") or []))
            if "--requirepass" in argv(oc) and "--requirepass" not in argv(c):
                flag("exposed", f"{key[1]}: redis --requirepass removed")
            en, eo = _env(c), _env(oc)
            if en.get("ALLOW_EMPTY_PASSWORD") == "yes" and eo.get("ALLOW_EMPTY_PASSWORD") != "yes":
                flag("exposed", f"{key[1]}: ALLOW_EMPTY_PASSWORD=yes")
            fresh = any(r["pod"] in w.get("pods_replaced", []) and r["volume"]["type"] in ("emptyDir", "container filesystem")
                        for r in dat) or w["fate"] == "created"
            for k2, v2 in (("POSTGRES_HOST_AUTH_METHOD", "trust"), ("MYSQL_ALLOW_EMPTY_PASSWORD", "yes"),
                           ("MYSQL_ALLOW_EMPTY_PASSWORD", "1")):
                if en.get(k2) == v2 and eo.get(k2) != v2 and fresh:
                    flag("exposed", f"{key[1]}: {k2}={v2} on a new data directory")
    for st in fx["steps"]:
        if st["type"] == "helm upgrade" and not st.get("render_error"):
            if ((st.get("values_new") or {}).get("auth") or {}).get("enabled") is False and \
                    ((st.get("values_now") or {}).get("auth") or {}).get("enabled") is not False and \
                    st.get("chart_name") in ("redis", "postgresql", "mariadb", "mysql", "mongodb") and \
                    not any(e.get("dry_run_error") for e in st["objects"]):
                flag("exposed", f"helm value auth.enabled false on chart {st.get('chart_name')}")
    for k, r in reach.items():
        if r.get("other_ns_before") is False and r.get("other_ns_after"):
            if any(s["exists_after"] and f"{k[0]} {k[1]}" in (s.get("backends_after") or []) for s in svcs.values()):
                flag("exposed", f"{k[0]} {k[1]} becomes reachable from any namespace")
    for who, verbs in D.rbac_new(fx).items():
        flag("exposed", f"{who} gains {', '.join(verbs)}")

    out["risky"] = out["lost"] or out["down"] or out["exposed"]
    return out
