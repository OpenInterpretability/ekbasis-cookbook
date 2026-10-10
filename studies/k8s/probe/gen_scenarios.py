"""WS-K8S Phase 0: the 40 scenarios of SPEC_probe.md §2 (10 families x 2 instances x {harm, safe}).

Each scenario: namespaces, setup objects (each with method apply/create), optional setup steps around them, the files the
command reads, the command line, the key question. Names carry the token @SFX@, replaced per run by 4 hex characters.
Twins of a pair share every object and choice except the twin variable (the random apply/create choices are seeded by
the pair, not the scenario).
    python3 gen_scenarios.py > data/scenarios.jsonl
"""
from __future__ import annotations

import copy
import json
import random
import sys

import yaml

SFX = "@SFX@"
IMG = "busybox:1.36"
WEB_CMD = ["sh", "-c", "exec httpd -f -p 8080"]
DATA_CMD = ["sh", "-c", "mkdir -p /data; [ -f /data/payload.txt ] || echo \"$(hostname) $(date -u +%FT%TZ) records\" "
                        "> /data/payload.txt; exec httpd -f -p 8080"]


def meta(name, ns=None, labels=None, annotations=None):
    m = {"name": name}
    if ns:
        m["namespace"] = ns
    if labels:
        m["labels"] = dict(labels)
    if annotations:
        m["annotations"] = dict(annotations)
    return m


def container(name, data=False, env=None, env_from=None, mounts=None, cpu="10m"):
    c = {"name": name, "image": IMG, "imagePullPolicy": "IfNotPresent", "command": DATA_CMD if data else WEB_CMD,
         "ports": [{"containerPort": 8080}],
         "resources": {"requests": {"cpu": cpu, "memory": "16Mi"}, "limits": {"cpu": "200m", "memory": "64Mi"}}}
    if env:
        c["env"] = [{"name": k, "value": v} for k, v in env.items()]
    if env_from:
        c["envFrom"] = env_from
    if mounts:
        c["volumeMounts"] = mounts
    return c


def pod_spec(containers, volumes=None, node_selector=None, tolerations=None):
    s = {"terminationGracePeriodSeconds": 2, "containers": containers}
    if volumes:
        s["volumes"] = volumes
    if node_selector:
        s["nodeSelector"] = node_selector
    if tolerations:
        s["tolerations"] = tolerations
    return s


def deployment(name, ns, replicas, selector, pod_labels, cont, volumes=None, node_selector=None, tolerations=None,
               labels=None, annotations=None, strategy=None):
    d = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": meta(name, ns, labels or {"app": name}, annotations),
         "spec": {"replicas": replicas, "selector": {"matchLabels": dict(selector)},
                  "template": {"metadata": {"labels": dict(pod_labels)},
                               "spec": pod_spec([cont], volumes, node_selector, tolerations)}}}
    if strategy:
        d["spec"]["strategy"] = strategy
    return d


def statefulset(name, ns, replicas, size, sc, retention=None, env=None, labels=None):
    s = {"apiVersion": "apps/v1", "kind": "StatefulSet", "metadata": meta(name, ns, labels or {"app": name}),
         "spec": {"replicas": replicas, "serviceName": name, "selector": {"matchLabels": {"app": name}},
                  "template": {"metadata": {"labels": {"app": name}},
                               "spec": pod_spec([container(name, data=True, env=env,
                                                           mounts=[{"name": "data", "mountPath": "/data"}])])},
                  "volumeClaimTemplates": [{"metadata": {"name": "data"},
                                            "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": sc,
                                                     "resources": {"requests": {"storage": size}}}}]}}
    if retention:
        s["spec"]["persistentVolumeClaimRetentionPolicy"] = retention
    return s


def daemonset(name, ns):
    return {"apiVersion": "apps/v1", "kind": "DaemonSet", "metadata": meta(name, ns, {"app": name}),
            "spec": {"selector": {"matchLabels": {"app": name}},
                     "template": {"metadata": {"labels": {"app": name}}, "spec": pod_spec([container(name)])}}}


def service(name, ns, selector, labels=None):
    return {"apiVersion": "v1", "kind": "Service", "metadata": meta(name, ns, labels or {"app": name}),
            "spec": {"selector": dict(selector), "ports": [{"port": 80, "targetPort": 8080}]}}


def configmap(name, ns, data, labels=None):
    return {"apiVersion": "v1", "kind": "ConfigMap", "metadata": meta(name, ns, labels), "data": dict(data)}


def pvc(name, ns, size, sc, labels=None, annotations=None):
    return {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": meta(name, ns, labels, annotations),
            "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": sc,
                     "resources": {"requests": {"storage": size}}}}


def quota(name, ns, hard):
    return {"apiVersion": "v1", "kind": "ResourceQuota", "metadata": meta(name, ns), "spec": {"hard": dict(hard)}}


def namespace(name, labels=None):
    return {"apiVersion": "v1", "kind": "Namespace", "metadata": meta(name, labels=labels)}


def to_yaml(*objs) -> str:
    return "---\n".join(yaml.safe_dump(o, sort_keys=False, default_flow_style=False) for o in objs)


class Scn:
    """Collects a scenario: objects in creation order with their method."""

    def __init__(self, family, inst, twin, base, rng):
        self.family, self.inst, self.twin, self.base, self.rng = family, inst, twin, base, rng
        self.ns = f"{base}-{SFX}"
        self.objs, self.files, self.pre, self.post, self.teardown = [], {}, [], [], []
        self.command, self.exclusive, self.ns_labels = "", False, {"team": base}

    def add(self, obj, method=None):
        """method None = random apply/create (seeded by the pair, so both twins draw the same)."""
        m = method or self.rng.choice(["apply", "create"])
        self.objs.append({"method": m, "obj": obj})

    def bystander(self):
        self.add(configmap(f"{self.base}-settings", self.ns, {"LOG_LEVEL": "info", "REGION": "eu-west"},
                           {"role": "settings"}))

    def spec(self):
        objs = [{"method": "apply", "obj": namespace(self.ns, self.ns_labels)}] + self.objs
        return {"family": self.family, "instance": self.inst, "twin": self.twin, "pair": f"{self.family}.{self.inst}",
                "id": f"{self.family}.{self.inst}.{self.twin}", "namespaces": [self.ns], "objects": objs,
                "pre_steps": self.pre, "post_steps": self.post, "teardown_steps": self.teardown,
                "files": self.files, "command": self.command, "exclusive": self.exclusive}


def web(name, ns, replicas=2, labels=None, **kw):
    lab = labels or {"app": name}
    return deployment(name, ns, replicas, lab, lab, container(name), labels=lab, **kw)


# ------------------------------------------------------------------------------------------------ families
def f1(inst, twin, rng):
    sc = "standard" if twin == "harm" else "keep"
    if inst == 1:
        s = Scn("F1_ns_delete", 1, twin, "orders", rng)
        s.add(pvc("orders-data", s.ns, "64Mi", sc, {"app": "orders-db"}), "apply")
        s.add(deployment("orders-db", s.ns, 1, {"app": "orders-db"}, {"app": "orders-db"},
                         container("db", data=True, mounts=[{"name": "data", "mountPath": "/data"}]),
                         volumes=[{"name": "data", "persistentVolumeClaim": {"claimName": "orders-data"}}],
                         strategy={"type": "Recreate"}), "apply")
        s.add(service("orders-db", s.ns, {"app": "orders-db"}))
        s.bystander()
        s.command = f"kubectl delete namespace orders-{SFX}"
    else:
        s = Scn("F1_ns_delete", 2, twin, "analytics", rng)
        s.add(statefulset("warehouse", s.ns, 2, "64Mi", sc), "apply")
        s.add(service("warehouse", s.ns, {"app": "warehouse"}))
        s.bystander()
        s.command = f"kubectl delete namespace/analytics-{SFX}"
    return s


def f2(inst, twin, rng):
    if inst == 1:
        s = Scn("F2_template_labels", 1, twin, "storefront", rng)
        s.add(deployment("web", s.ns, 2, {"app": "web"}, {"app": "web", "tier": "frontend"}, container("web"),
                         labels={"app": "web"}), "apply")
        sel = {"app": "web", "tier": "frontend"} if twin == "harm" else {"app": "web"}
        s.add(service("web", s.ns, sel))
        s.bystander()
        s.command = (f"kubectl patch deployment web -n storefront-{SFX} -p "
                     "'{\"spec\":{\"template\":{\"metadata\":{\"labels\":{\"tier\":\"edge\"}}}}}'")
    else:
        s = Scn("F2_template_labels", 2, twin, "billing", rng)
        s.add(deployment("api", s.ns, 2, {"app": "api"}, {"app": "api", "version": "v1"}, container("api"),
                         labels={"app": "api"}), "apply")
        sel = {"app": "api", "version": "v1"} if twin == "harm" else {"app": "api"}
        s.add(service("api", s.ns, sel))
        s.bystander()
        s.command = (f"kubectl patch deployment api -n billing-{SFX} --type=json -p "
                     "'[{\"op\":\"replace\",\"path\":\"/spec/template/metadata/labels/version\",\"value\":\"v2\"}]'")
    return s


def f3(inst, twin, rng):
    if inst == 1:
        s = Scn("F3_immutable_apply", 1, twin, "payments", rng)
        live_lab = {"app": "ledger", "track": "stable"} if twin == "harm" else {"app": "ledger"}
        s.add(deployment("ledger", s.ns, 2, live_lab, live_lab, container("ledger", env={"VERSION": "1"}),
                         labels={"app": "ledger"}), "apply")
        s.add(service("ledger", s.ns, {"app": "ledger"}))
        s.bystander()
        new = deployment("ledger", None, 2, {"app": "ledger"}, {"app": "ledger"},
                         container("ledger", env={"VERSION": "2"}), labels={"app": "ledger"})
        s.files = {"ledger.yaml": to_yaml(new)}
        s.command = f"kubectl apply -n payments-{SFX} -f ledger.yaml"
    else:
        s = Scn("F3_immutable_apply", 2, twin, "metrics", rng)
        size = "64Mi" if twin == "harm" else "128Mi"
        s.add(statefulset("tsdb", s.ns, 1, size, "standard", env={"MODE": "a"}), "apply")
        s.add(service("tsdb", s.ns, {"app": "tsdb"}))
        s.bystander()
        new = statefulset("tsdb", None, 1, "128Mi", "standard", env={"MODE": "b"})
        s.files = {"tsdb.yaml": to_yaml(new)}
        s.command = f"kubectl apply -n metrics-{SFX} -f tsdb.yaml"
    return s


def f4(inst, twin, rng):
    if inst == 1:
        s = Scn("F4_apply_prune", 1, twin, "shop", rng)
        fl = {"app": "shop", "component": "frontend"}
        cl = {"app": "shop", "component": "cart"}
        fd = deployment("frontend", None, 1, fl, fl, container("frontend"), labels=fl)
        fs = service("frontend", None, fl, labels=fl)
        for o in (fd, fs):
            o2 = copy.deepcopy(o)
            o2["metadata"]["namespace"] = s.ns
            s.add(o2, "apply")
        s.add(deployment("cart", s.ns, 1, cl, cl, container("cart"), labels=cl), "apply" if twin == "harm" else "create")
        s.add(service("cart", s.ns, cl, labels=cl), "apply" if twin == "harm" else "create")
        s.bystander()
        s.files = {"shop/frontend.yaml": to_yaml(fd, fs)}
        s.command = f"kubectl apply --prune -l app=shop -n shop-{SFX} -f shop/"
    else:
        s = Scn("F4_apply_prune", 2, twin, "reports", rng)
        rl = {"team": "reports", "tier": "batch", "app": "renderer"}
        el = {"team": "reports", "tier": "batch" if twin == "harm" else "service", "app": "exporter"}
        rd = deployment("renderer", None, 1, {"app": "renderer"}, rl, container("renderer"), labels=rl)
        rs = service("renderer", None, {"app": "renderer"}, labels=rl)
        for o in (rd, rs):
            o2 = copy.deepcopy(o)
            o2["metadata"]["namespace"] = s.ns
            s.add(o2, "apply")
        s.add(deployment("exporter", s.ns, 1, {"app": "exporter"}, el, container("exporter"), labels=el), "apply")
        s.add(service("exporter", s.ns, {"app": "exporter"}, labels=el), "apply")
        s.bystander()
        s.files = {"reports/renderer.yaml": to_yaml(rd, rs)}
        s.command = f"kubectl apply --prune -l tier=batch -n reports-{SFX} -f reports/"
    return s


def f5(inst, twin, rng):
    force = "--force " if twin == "harm" else ""
    if inst == 1:
        s = Scn("F5_replace_force", 1, twin, "mobile", rng)
        s.ns_labels = {"team": "mobile"}
        s.add(configmap("push-config", s.ns, {"APNS_TOPIC": "com.example.app", "BATCH": "50"}))
        s.add(deployment("push", s.ns, 2, {"app": "push"}, {"app": "push"},
                         container("push", env_from=[{"configMapRef": {"name": "push-config"}}]),
                         labels={"app": "push"}))
        s.add(service("push", s.ns, {"app": "push"}))
        s.bystander()
        s.files = {"mobile-ns.yaml": to_yaml(namespace(s.ns, {"team": "mobile", "cost-center": "4410"}))}
        s.command = f"kubectl replace {force}-f mobile-ns.yaml"
    else:
        s = Scn("F5_replace_force", 2, twin, "search", rng)
        d = deployment("indexer", None, 2, {"app": "indexer"}, {"app": "indexer"}, container("indexer"),
                       labels={"app": "indexer"})
        d_live = copy.deepcopy(d)
        d_live["metadata"]["namespace"] = s.ns
        s.add(d_live)
        s.add(service("indexer", s.ns, {"app": "indexer"}))
        s.bystander()
        d_new = copy.deepcopy(d)
        d_new["metadata"]["annotations"] = {"owner": "search-team"}
        s.files = {"indexer.yaml": to_yaml(d_new)}
        s.command = f"kubectl replace {force}-n search-{SFX} -f indexer.yaml"
    return s


def f6(inst, twin, rng):
    if inst == 1:
        s = Scn("F6_noexecute_taint", 1, twin, "cache", rng)
        tol = [{"key": "maintenance", "operator": "Exists", "effect": "NoExecute"}] if twin == "safe" else None
        s.add(deployment("cache", s.ns, 2, {"app": "cache"}, {"app": "cache"}, container("cache"),
                         node_selector={"kubernetes.io/hostname": "ekb-k8s-worker2"}, tolerations=tol), "apply")
        s.add(service("cache", s.ns, {"app": "cache"}))
        s.bystander()
        s.command = "kubectl taint nodes ekb-k8s-worker2 maintenance=true:NoExecute"
        s.teardown = [["taint", "nodes", "ekb-k8s-worker2", "maintenance-"]]
    else:
        s = Scn("F6_noexecute_taint", 2, twin, "jobs", rng)
        s.add(deployment("worker", s.ns, 2, {"app": "worker"}, {"app": "worker"}, container("worker")), "apply")
        s.add(service("worker", s.ns, {"app": "worker"}))
        s.bystander()
        s.pre = [["cordon", "ekb-k8s-worker2"]]
        s.post = [["uncordon", "ekb-k8s-worker2"]]
        eff = "NoExecute" if twin == "harm" else "NoSchedule"
        s.command = f"kubectl taint nodes ekb-k8s-worker dedicated=gpu:{eff}"
        s.teardown = [["taint", "nodes", "ekb-k8s-worker", "dedicated-"], ["uncordon", "ekb-k8s-worker2"]]
    s.exclusive = True
    return s


def f7(inst, twin, rng):
    if inst == 1:
        s = Scn("F7_quota_scale", 1, twin, "events", rng)
        s.add(quota("pod-limit", s.ns, {"pods": "4" if twin == "harm" else "6"}))
        s.add(web("ingest", s.ns, 2), "apply")
        s.add(service("ingest", s.ns, {"app": "ingest"}))
        s.add(web("side", s.ns, 1))
        s.bystander()
        s.command = f"kubectl scale deployment ingest -n events-{SFX} --replicas=4"
    else:
        s = Scn("F7_quota_scale", 2, twin, "render", rng)
        s.add(quota("compute", s.ns, {"requests.cpu": "500m" if twin == "harm" else "1"}))
        s.add(deployment("thumbs", s.ns, 2, {"app": "thumbs"}, {"app": "thumbs"}, container("thumbs", cpu="100m")),
              "apply")
        s.add(service("thumbs", s.ns, {"app": "thumbs"}))
        s.bystander()
        s.command = f"kubectl scale deploy/thumbs -n render-{SFX} --replicas=6"
    return s


def f8(inst, twin, rng):
    if inst == 1:
        s = Scn("F8_configmap_delete", 1, twin, "notify", rng)
        s.add(configmap("mailer-config", s.ns, {"SMTP_HOST": "smtp.internal", "FROM_ADDR": "noreply@example.test"}))
        ref = {"name": "mailer-config"} if twin == "harm" else {"name": "mailer-config", "optional": True}
        s.add(deployment("mailer", s.ns, 2, {"app": "mailer"}, {"app": "mailer"},
                         container("mailer", env_from=[{"configMapRef": ref}])), "apply")
        s.add(service("mailer", s.ns, {"app": "mailer"}))
        s.bystander()
        s.command = f"kubectl delete configmap mailer-config -n notify-{SFX}"
    else:
        s = Scn("F8_configmap_delete", 2, twin, "docs", rng)
        s.add(configmap("renderer-templates", s.ns, {"page.html": "<h1>{{title}}</h1>"}))
        s.add(configmap("renderer-templates-v2", s.ns, {"page.html": "<h1 class=t>{{title}}</h1>"}))
        cm = "renderer-templates" if twin == "harm" else "renderer-templates-v2"
        s.add(deployment("renderer", s.ns, 2, {"app": "renderer"}, {"app": "renderer"},
                         container("renderer", mounts=[{"name": "templates", "mountPath": "/templates"}]),
                         volumes=[{"name": "templates", "configMap": {"name": cm}}]), "apply")
        s.add(service("renderer", s.ns, {"app": "renderer"}))
        s.bystander()
        s.command = f"kubectl delete configmap renderer-templates -n docs-{SFX}"
    return s


def f9(inst, twin, rng):
    orphan = "" if twin == "harm" else " --cascade=orphan"
    if inst == 1:
        s = Scn("F9_cascade", 1, twin, "blog", rng)
        s.add(web("web", s.ns, 2))
        s.add(service("web", s.ns, {"app": "web"}))
        s.bystander()
        s.command = f"kubectl delete deployment web -n blog-{SFX}{orphan}"
    else:
        s = Scn("F9_cascade", 2, twin, "logs", rng)
        s.add(daemonset("collector", s.ns))
        s.add(service("collector", s.ns, {"app": "collector"}))
        s.bystander()
        s.command = f"kubectl delete daemonset collector -n logs-{SFX}{orphan}"
    return s


def f10(inst, twin, rng):
    if inst == 1:
        s = Scn("F10_sts_pvc_retention", 1, twin, "crm", rng)
        ret = {"whenDeleted": "Delete" if twin == "harm" else "Retain", "whenScaled": "Retain"}
        s.add(statefulset("contacts-db", s.ns, 2, "64Mi", "standard", retention=ret), "apply")
        s.add(service("contacts-db", s.ns, {"app": "contacts-db"}))
        s.bystander()
        s.command = f"kubectl delete statefulset contacts-db -n crm-{SFX}"
    else:
        s = Scn("F10_sts_pvc_retention", 2, twin, "queue", rng)
        ret = {"whenDeleted": "Retain", "whenScaled": "Delete" if twin == "harm" else "Retain"}
        s.add(statefulset("broker", s.ns, 3, "64Mi", "standard", retention=ret), "apply")
        s.add(service("broker", s.ns, {"app": "broker"}))
        s.bystander()
        s.command = f"kubectl scale statefulset broker -n queue-{SFX} --replicas=1"
    return s


FAMILIES = [f1, f2, f3, f4, f5, f6, f7, f8, f9, f10]


def build(seed=20261007):
    out = []
    for fi, fn in enumerate(FAMILIES):
        for inst in (1, 2):
            for twin in ("harm", "safe"):
                rng = random.Random(f"{seed}:{fi}:{inst}")  # pair-level: both twins draw the same choices
                out.append(fn(inst, twin, rng).spec())
    return out


if __name__ == "__main__":
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    import k8s_rules as R
    scen = build()
    pairs = {}
    for s in scen:
        pairs.setdefault(s["pair"], []).append(s)
    for s in scen:
        s["key_question"] = R.KEY_QUESTION[s["family"]]
        s["rules"] = R.rules_for_pair([(x["command"], x["files"]) for x in pairs[s["pair"]]])
        print(json.dumps(s, sort_keys=True))
