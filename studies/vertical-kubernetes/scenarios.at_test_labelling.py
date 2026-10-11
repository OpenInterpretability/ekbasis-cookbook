"""Kubernetes change scenarios, ALL WRITTEN BY US (Claude, this session) for the pilot. Nothing comes from a real repo.

Each scenario runs in its own namespace s<id> of a local kind cluster:
  v1     steps that build the starting point (kubectl apply of our manifests, or helm install of a bitnami chart)
  seed   data written after v1 (a token the runner searches for afterwards)
  probes client endpoints probed every 0.2 s during the change (from the namespace vk-probe)
  v2     the change under test: kubectl apply / kubectl delete / helm upgrade / helm uninstall
Expected outcomes are NOT stored here: labels come only from execution (runner.py).
split: "dev" (used to build the state builder; Ekbasis may be called on them) or "test" (frozen by hash before any call).
"""
from __future__ import annotations

import copy

PG_PW = "pgpass-7c1d"        # test credentials of the throwaway cluster, never shown to the model
RD_PW = "rdpass-91be"
NGINX_A, NGINX_B, NGINX_BAD = "nginx:1.26-alpine", "nginx:1.27-alpine", "nginx:1.27.99-doesnotexist"
PG_IMG, RD_IMG, RD_IMG_B = "postgres:17-alpine", "redis:7-alpine", "redis:7.4-alpine"
CHARTS = "charts"   # bitnami charts pulled from oci://registry-1.docker.io/bitnamicharts (nginx 25.2.1, postgresql 18.12.4, redis 28.3.1)


# ---------------------------------------------------------------- manifest builders

def secret(name, data):
    return {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name}, "type": "Opaque", "stringData": data}


def svc(name, selector, port, target=None, typ="ClusterIP", node_port=None, port_name=None):
    p = {"port": port, "targetPort": target if target is not None else port, "protocol": "TCP"}
    if port_name:
        p["name"] = port_name
    if node_port:
        p["nodePort"] = node_port
    return {"apiVersion": "v1", "kind": "Service", "metadata": {"name": name},
            "spec": {"type": typ, "selector": selector, "ports": [p]}}


def http_probe(path="/", port=80):
    return {"httpGet": {"path": path, "port": port}, "periodSeconds": 1, "failureThreshold": 2}


def web(name="web", replicas=1, image=NGINX_A, probe=True, strategy=None, command=None, labels=None, extra=None,
        port_name=None, volumes=None, mounts=None, resources=None, host_port=None, prestop=False):
    lab = {"app": name}
    tl = dict(lab, **(labels or {}))
    c = {"name": "nginx", "image": image, "ports": [{"containerPort": 80}]}
    if port_name:
        c["ports"][0]["name"] = port_name
    if host_port:
        c["ports"][0]["hostPort"] = host_port
    if probe:
        c["readinessProbe"] = probe if isinstance(probe, dict) else http_probe()
    if command:
        c["command"] = command
    if mounts:
        c["volumeMounts"] = mounts
    if resources:
        c["resources"] = resources
    if prestop:
        c["lifecycle"] = {"preStop": {"exec": {"command": ["sleep", "3"]}}}
    spec = {"replicas": replicas, "selector": {"matchLabels": lab},
            "template": {"metadata": {"labels": tl}, "spec": {"containers": [c], "terminationGracePeriodSeconds": 10}}}
    if volumes:
        spec["template"]["spec"]["volumes"] = volumes
    if strategy:
        spec["strategy"] = strategy
    d = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name}, "spec": spec}
    if extra:
        extra(d)
    return d


RECREATE = {"type": "Recreate"}


def ru(surge, unavail):
    return {"type": "RollingUpdate", "rollingUpdate": {"maxSurge": surge, "maxUnavailable": unavail}}


def pg_container(probe=True, env_extra=None, mount=True, image=PG_IMG):
    c = {"name": "postgres", "image": image, "ports": [{"containerPort": 5432}],
         "env": [{"name": "POSTGRES_USER", "value": "app"}, {"name": "POSTGRES_DB", "value": "appdb"},
                 {"name": "POSTGRES_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "pg-secret", "key": "password"}}}]
                + (env_extra or [])}
    if probe:
        c["readinessProbe"] = {"exec": {"command": ["pg_isready", "-U", "app", "-d", "appdb"]}, "periodSeconds": 1,
                               "failureThreshold": 2}
    if mount:
        c["volumeMounts"] = [{"name": "data", "mountPath": "/var/lib/postgresql/data"}]
    return c


def pg_sts(probe=True, env_extra=None, sc="standard", size="1Gi", retention=None, update=None, pmp=None, replicas=1,
           image=PG_IMG):
    spec = {"serviceName": "pg", "replicas": replicas, "selector": {"matchLabels": {"app": "pg"}},
            "template": {"metadata": {"labels": {"app": "pg"}},
                         "spec": {"terminationGracePeriodSeconds": 20,
                                  "containers": [pg_container(probe, env_extra, image=image)]}},
            "volumeClaimTemplates": [{"metadata": {"name": "data"},
                                      "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": sc,
                                               "resources": {"requests": {"storage": size}}}}]}
    if retention:
        spec["persistentVolumeClaimRetentionPolicy"] = retention
    if update:
        spec["updateStrategy"] = update
    if pmp:
        spec["podManagementPolicy"] = pmp
    return {"apiVersion": "apps/v1", "kind": "StatefulSet", "metadata": {"name": "pg"}, "spec": spec}


def pg_dep(volume, env_extra=None, strategy=None, probe=True):
    """postgres in a Deployment; volume: 'emptydir' | 'none' | 'pvc'."""
    c = pg_container(probe, env_extra, mount=volume != "none")
    spec = {"replicas": 1, "selector": {"matchLabels": {"app": "pg"}},
            "template": {"metadata": {"labels": {"app": "pg"}},
                         "spec": {"terminationGracePeriodSeconds": 20, "containers": [c]}}}
    if volume == "emptydir":
        spec["template"]["spec"]["volumes"] = [{"name": "data", "emptyDir": {}}]
    elif volume == "pvc":
        spec["template"]["spec"]["volumes"] = [{"name": "data", "persistentVolumeClaim": {"claimName": "pg-data"}}]
    if strategy:
        spec["strategy"] = strategy
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "pg"}, "spec": spec}


def pvc(name, sc="standard", size="1Gi"):
    return {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": name},
            "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": sc,
                     "resources": {"requests": {"storage": size}}}}


def pg_base():
    return [secret("pg-secret", {"password": PG_PW}), svc("pg", {"app": "pg"}, 5432)]


def rd_container(args_extra=None, probe=True, mount=True, image=RD_IMG, auth=True):
    args = (["--requirepass", "$(REDIS_PASSWORD)"] if auth else []) + (args_extra or [])
    c = {"name": "redis", "image": image, "args": args, "ports": [{"containerPort": 6379}],
         "env": [{"name": "REDIS_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "rd-secret", "key": "password"}}}]}
    if probe:
        c["readinessProbe"] = {"exec": {"command": ["sh", "-c",
                                                    'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping | grep -q PONG']},
                               "periodSeconds": 1, "failureThreshold": 2}
    if mount:
        c["volumeMounts"] = [{"name": "data", "mountPath": "/data"}]
    return c


def rd_sts(args_extra=None, probe=True, image=RD_IMG, auth=True, env_extra=None):
    c = rd_container(args_extra, probe, image=image, auth=auth)
    c["env"] += env_extra or []
    return {"apiVersion": "apps/v1", "kind": "StatefulSet", "metadata": {"name": "redis"},
            "spec": {"serviceName": "redis", "replicas": 1, "selector": {"matchLabels": {"app": "redis"}},
                     "template": {"metadata": {"labels": {"app": "redis"}},
                                  "spec": {"terminationGracePeriodSeconds": 20, "containers": [c]}},
                     "volumeClaimTemplates": [{"metadata": {"name": "data"},
                                               "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": "standard",
                                                        "resources": {"requests": {"storage": "1Gi"}}}}]}}


def rd_dep(volume, args_extra=None, image=RD_IMG, probe=True):
    c = rd_container(args_extra, probe, mount=volume != "none", image=image)
    spec = {"replicas": 1, "selector": {"matchLabels": {"app": "redis"}},
            "template": {"metadata": {"labels": {"app": "redis"}},
                         "spec": {"terminationGracePeriodSeconds": 20, "containers": [c]}}}
    if volume == "emptydir":
        spec["template"]["spec"]["volumes"] = [{"name": "data", "emptyDir": {}}]
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "redis"}, "spec": spec}


def rd_base():
    return [secret("rd-secret", {"password": RD_PW}), svc("redis", {"app": "redis"}, 6379)]


def role(name, rules):
    return {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role", "metadata": {"name": name}, "rules": rules}


def rolebinding(name, role_name, subjects, cluster_role=False):
    return {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding", "metadata": {"name": name},
            "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole" if cluster_role else "Role",
                        "name": role_name}, "subjects": subjects}


def crb(name, role_name, subjects):
    return {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding", "metadata": {"name": name},
            "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": role_name},
            "subjects": subjects}


def sa(ns_name="@NS@", name="default"):
    return {"kind": "ServiceAccount", "name": name, "namespace": ns_name}


def netpol(name, pod_selector, from_):
    return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": name},
            "spec": {"podSelector": pod_selector, "policyTypes": ["Ingress"], "ingress": [{"from": from_}]}}


CLIENT_NS = [{"namespaceSelector": {"matchLabels": {"role": "client"}}}]


def cm(name, data):
    return {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name}, "data": data}


def pdb(name, sel, min_av):
    return {"apiVersion": "policy/v1", "kind": "PodDisruptionBudget", "metadata": {"name": name},
            "spec": {"minAvailable": min_av, "selector": {"matchLabels": sel}}}


def mod(obj, fn):
    o = copy.deepcopy(obj)
    fn(o)
    return o


# ---------------------------------------------------------------- probes, seeds

P_WEB = {"name": "web", "type": "http", "host": "web", "port": 80}
P_PG = {"name": "pg", "type": "pg", "host": "pg", "port": 5432, "user": "app", "password": PG_PW, "db": "appdb"}
P_RD = {"name": "redis", "type": "redis", "host": "redis", "port": 6379, "password": RD_PW}
SEED_PG = {"op": "pg", "pod": "app=pg", "user": "app", "password": PG_PW, "db": "appdb"}
SEED_RD = {"op": "redis", "pod": "app=redis", "password": RD_PW}


def apply(*objs):
    return {"apply": list(objs)}


def delete(*refs):
    return {"delete": list(refs)}


def helm(release, chart, values):
    return {"helm": {"release": release, "chart": chart, "values": values}}


def web_base(**kw):
    return [web(**kw), svc("web", {"app": "web"}, 80)]


# helm values
HPG = {"auth": {"username": "app", "password": PG_PW, "database": "appdb", "postgresPassword": PG_PW + "-admin"},
       "primary": {"persistence": {"size": "1Gi"}, "resourcesPreset": "small"}}
HRD = {"architecture": "standalone", "auth": {"password": RD_PW}, "master": {"resourcesPreset": "small",
                                                                              "persistence": {"size": "1Gi"}}}
HNG = {"service": {"type": "ClusterIP"}, "replicaCount": 1}


def hv(base, **patch):
    out = copy.deepcopy(base)
    for path, v in patch.items():
        cur = out
        ks = path.split("__")
        for k in ks[:-1]:
            cur = cur.setdefault(k, {})
        cur[ks[-1]] = v
    return out


P_HPG = dict(P_PG, name="db", host="db-postgresql")
P_HRD = dict(P_RD, name="rd", host="rd-redis-master")
P_HNG = {"name": "web", "type": "http", "host": "web-nginx", "port": 80}
SEED_HPG = dict(SEED_PG, pod="app.kubernetes.io/instance=db")
SEED_HRD = dict(SEED_RD, pod="app.kubernetes.io/instance=rd")

NGINX_CONF = "server { listen 80; location / { return 200 'v%s\\n'; } }"


def S_(i, split, family, title, v1, v2, probes, seed=()):
    return {"id": i, "split": split, "family": family, "title": title, "v1": v1, "v2": v2, "probes": probes,
            "seed": list(seed)}


ROLE_CM = role("app-reader", [{"apiGroups": [""], "resources": ["configmaps"], "verbs": ["get", "list"]}])
RB_DEFAULT = rolebinding("app-reader", "app-reader", [sa()])
NP_CLIENTS = netpol("web-clients", {"matchLabels": {"app": "web"}}, CLIENT_NS)

S = [
    # ------------------------------------------------------------ DEV (state builder developed on these)
    S_(1, "dev", "rollout", "3 replicas, readiness probe, rolling update, image bump",
       [apply(*web_base(replicas=3))], [apply(web(replicas=3, image=NGINX_B))], [P_WEB]),
    S_(2, "dev", "rollout", "1 replica, no probe, default rolling update, image bump",
       [apply(*web_base(probe=False))], [apply(web(probe=False, image=NGINX_B))], [P_WEB]),
    S_(3, "dev", "rollout", "1 replica, probe, maxSurge 0 / maxUnavailable 1, image bump",
       [apply(*web_base(strategy=ru(0, 1)))], [apply(web(strategy=ru(0, 1), image=NGINX_B))], [P_WEB]),
    S_(4, "dev", "service", "Service selector changed to a label no pod has",
       [apply(*web_base(replicas=2))], [apply(svc("web", {"app": "web", "tier": "frontend"}, 80))], [P_WEB]),
    S_(5, "dev", "rollout", "Recreate, 2 replicas with probe, image bump",
       [apply(*web_base(replicas=2, strategy=RECREATE))], [apply(web(replicas=2, strategy=RECREATE, image=NGINX_B))],
       [P_WEB]),
    S_(6, "dev", "statefulset", "postgres StatefulSet (1 replica, probe, PVC): env added to the pod template",
       [apply(*pg_base(), pg_sts())], [apply(pg_sts(env_extra=[{"name": "TZ", "value": "UTC"}]))], [P_PG], [SEED_PG]),
    S_(7, "dev", "statefulset", "postgres StatefulSet: volumeClaimTemplates storage 1Gi -> 2Gi",
       [apply(*pg_base(), pg_sts())], [apply(pg_sts(size="2Gi"))], [P_PG], [SEED_PG]),
    S_(8, "dev", "data", "postgres Deployment on emptyDir: env added to the pod template",
       [apply(*pg_base(), pg_dep("emptydir"))], [apply(pg_dep("emptydir", env_extra=[{"name": "TZ", "value": "UTC"}]))],
       [P_PG], [SEED_PG]),
    S_(9, "dev", "data", "redis Deployment with no volume: image 7 -> 7.4",
       [apply(*rd_base(), rd_dep("none"))], [apply(rd_dep("none", image=RD_IMG_B))], [P_RD], [SEED_RD]),
    S_(10, "dev", "data", "redis StatefulSet on a PVC with --save '' --appendonly no: env added",
       [apply(*rd_base(), rd_sts(["--save", "", "--appendonly", "no"]))],
       [apply(rd_sts(["--save", "", "--appendonly", "no"], env_extra=[{"name": "TZ", "value": "UTC"}]))],
       [P_RD], [SEED_RD]),
    S_(11, "dev", "exposure", "web Service ClusterIP -> NodePort",
       [apply(*web_base(replicas=2))], [apply(svc("web", {"app": "web"}, 80, typ="NodePort"))], [P_WEB]),
    S_(12, "dev", "rbac", "Role bound to the namespace default ServiceAccount gains get/list on secrets",
       [apply(*web_base(), ROLE_CM, RB_DEFAULT)],
       [apply(role("app-reader", [{"apiGroups": [""], "resources": ["configmaps", "secrets"],
                                   "verbs": ["get", "list"]}]))], [P_WEB]),
    S_(13, "dev", "netpol", "NetworkPolicy podSelector changed so it no longer selects the web pods",
       [apply(*web_base(), NP_CLIENTS)],
       [apply(netpol("web-clients", {"matchLabels": {"app": "web-old"}}, CLIENT_NS))], [P_WEB]),
    S_(14, "dev", "pvc", "kubectl delete pvc of a running postgres StatefulSet pod (pod keeps running)",
       [apply(*pg_base(), pg_sts())], [delete(("persistentvolumeclaim", "data-pg-0"))], [P_PG], [SEED_PG]),
    S_(15, "dev", "pvc", "delete a postgres StatefulSet whose PVC retention policy is whenDeleted: Delete",
       [apply(*pg_base(), pg_sts(retention={"whenDeleted": "Delete", "whenScaled": "Retain"}))],
       [delete(("statefulset", "pg"))], [P_PG], [SEED_PG]),
    S_(16, "dev", "helm", "helm upgrade of bitnami/nginx with a values file that sets only replicaCount (service.type falls back to the chart default)",
       [helm("web", "nginx", HNG)], [helm("web", "nginx", {"replicaCount": 1})], [P_HNG]),
    S_(17, "dev", "helm", "helm upgrade of bitnami/postgresql with primary.persistence.size 1Gi -> 2Gi",
       [helm("db", "postgresql", HPG)], [helm("db", "postgresql", hv(HPG, primary__persistence__size="2Gi"))],
       [P_HPG], [SEED_HPG]),
    S_(18, "dev", "rollout", "web scaled from 2 replicas to 0",
       [apply(*web_base(replicas=2))], [apply(web(replicas=0))], [P_WEB]),

    # ------------------------------------------------------------ TEST (frozen by hash before any Ekbasis call)
    S_(19, "test", "rollout", "2 replicas, probe, preStop sleep, rolling update, image bump",
       [apply(*web_base(replicas=2, prestop=True))], [apply(web(replicas=2, prestop=True, image=NGINX_B))], [P_WEB]),
    S_(20, "test", "rollout", "1 replica, no probe, rolling update, new command sleeps 8 s before starting nginx",
       [apply(*web_base(probe=False))],
       [apply(web(probe=False, command=["sh", "-c", "sleep 8; exec nginx -g 'daemon off;'"]))], [P_WEB]),
    S_(21, "test", "rollout", "3 replicas, no probe, maxUnavailable 100%, image bump",
       [apply(*web_base(replicas=3, probe=False, strategy=ru(0, "100%")))],
       [apply(web(replicas=3, probe=False, strategy=ru(0, "100%"), image=NGINX_B))], [P_WEB]),
    S_(22, "test", "rollout", "2 replicas, probe, maxSurge 0 / maxUnavailable 2, image bump",
       [apply(*web_base(replicas=2, strategy=ru(0, 2)))], [apply(web(replicas=2, strategy=ru(0, 2), image=NGINX_B))],
       [P_WEB]),
    S_(23, "test", "rollout", "Recreate Deployment: only an annotation on the Deployment object changes",
       [apply(*web_base(replicas=2, strategy=RECREATE))],
       [apply(web(replicas=2, strategy=RECREATE,
                  extra=lambda d: d["metadata"].__setitem__("annotations", {"team": "payments"})))], [P_WEB]),
    S_(24, "test", "rollout", "Recreate, 2 replicas, image bump",
       [apply(*web_base(replicas=2, strategy=RECREATE, probe=False))],
       [apply(web(replicas=2, strategy=RECREATE, probe=False, image=NGINX_B))], [P_WEB]),
    S_(25, "test", "image", "2 replicas, probe, rolling update to an image tag that does not exist",
       [apply(*web_base(replicas=2))], [apply(web(replicas=2, image=NGINX_BAD))], [P_WEB]),
    S_(26, "test", "image", "Recreate to an image tag that does not exist",
       [apply(*web_base(strategy=RECREATE))], [apply(web(strategy=RECREATE, image=NGINX_BAD))], [P_WEB]),
    S_(27, "test", "image", "1 replica, no probe, default rolling update to an image tag that does not exist",
       [apply(*web_base(probe=False))], [apply(web(probe=False, image=NGINX_BAD))], [P_WEB]),
    S_(28, "test", "immutable", "Deployment spec.selector changed (adds a label)",
       [apply(*web_base(replicas=2))],
       [apply(web(replicas=2, labels={"tier": "fe"},
                  extra=lambda d: d["spec"]["selector"]["matchLabels"].__setitem__("tier", "fe")))], [P_WEB]),
    S_(29, "test", "probe", "readiness probe changed to a path that returns 404, 2 replicas, rolling update",
       [apply(*web_base(replicas=2))], [apply(web(replicas=2, probe=http_probe("/healthz")))], [P_WEB]),
    S_(30, "test", "probe", "readiness probe changed to a path that returns 404, Recreate",
       [apply(*web_base(replicas=2, strategy=RECREATE))],
       [apply(web(replicas=2, strategy=RECREATE, probe=http_probe("/healthz")))], [P_WEB]),
    S_(31, "test", "service", "Service targetPort 80 -> 8080 (nginx listens on 80)",
       [apply(*web_base(replicas=2))], [apply(svc("web", {"app": "web"}, 80, target=8080))], [P_WEB]),
    S_(32, "test", "service", "Service targetPort is the named port 'http'; the pod template renames the port to 'web'",
       [apply(web(replicas=2, port_name="http"), svc("web", {"app": "web"}, 80, target="http"))],
       [apply(web(replicas=2, port_name="web"))], [P_WEB]),
    S_(33, "test", "config", "ConfigMap mounted as nginx config changes its response text",
       [apply(cm("web-conf", {"default.conf": NGINX_CONF % 1}),
              web(replicas=2, volumes=[{"name": "conf", "configMap": {"name": "web-conf"}}],
                  mounts=[{"name": "conf", "mountPath": "/etc/nginx/conf.d"}]), svc("web", {"app": "web"}, 80))],
       [apply(cm("web-conf", {"default.conf": NGINX_CONF % 2}))], [P_WEB]),
    S_(34, "test", "delete", "kubectl delete deployment web",
       [apply(*web_base(replicas=2))], [delete(("deployment", "web"))], [P_WEB]),
    S_(35, "test", "rollout", "PDB minAvailable 2 on a 2-replica Recreate Deployment, image bump",
       [apply(*web_base(replicas=2, strategy=RECREATE), pdb("web", {"app": "web"}, 2))],
       [apply(web(replicas=2, strategy=RECREATE, image=NGINX_B))], [P_WEB]),
    S_(36, "test", "rollout", "scale 3 -> 1 replicas (probe)",
       [apply(*web_base(replicas=3))], [apply(web(replicas=1))], [P_WEB]),
    S_(37, "test", "rollout", "2 replicas, probe: a label added to the pod template",
       [apply(*web_base(replicas=2))], [apply(web(replicas=2, labels={"version": "b"}))], [P_WEB]),
    S_(38, "test", "rollout", "2 replicas, probe, rolling update: memory limit set to 1Mi",
       [apply(*web_base(replicas=2))],
       [apply(web(replicas=2, resources={"limits": {"memory": "1Mi"}}))], [P_WEB]),
    S_(39, "test", "statefulset", "postgres StatefulSet with no readiness probe: env added",
       [apply(*pg_base(), pg_sts(probe=False))],
       [apply(pg_sts(probe=False, env_extra=[{"name": "TZ", "value": "UTC"}]))], [P_PG], [SEED_PG]),
    S_(40, "test", "statefulset", "postgres StatefulSet with probe: resource requests added",
       [apply(*pg_base(), pg_sts())],
       [apply(mod(pg_sts(), lambda o: o["spec"]["template"]["spec"]["containers"][0].__setitem__(
           "resources", {"requests": {"cpu": "50m", "memory": "64Mi"}})))], [P_PG], [SEED_PG]),
    S_(41, "test", "statefulset", "postgres StatefulSet updateStrategy OnDelete, no probe: env added",
       [apply(*pg_base(), pg_sts(probe=False, update={"type": "OnDelete"}))],
       [apply(pg_sts(probe=False, update={"type": "OnDelete"}, env_extra=[{"name": "TZ", "value": "UTC"}]))],
       [P_PG], [SEED_PG]),
    S_(42, "test", "statefulset", "postgres StatefulSet RollingUpdate partition 1 (1 replica), no probe: env added",
       [apply(*pg_base(), pg_sts(probe=False, update={"type": "RollingUpdate", "rollingUpdate": {"partition": 1}}))],
       [apply(pg_sts(probe=False, update={"type": "RollingUpdate", "rollingUpdate": {"partition": 1}},
                     env_extra=[{"name": "TZ", "value": "UTC"}]))], [P_PG], [SEED_PG]),
    S_(43, "test", "immutable", "postgres StatefulSet podManagementPolicy OrderedReady -> Parallel",
       [apply(*pg_base(), pg_sts())], [apply(pg_sts(pmp="Parallel"))], [P_PG], [SEED_PG]),
    S_(44, "test", "delete", "kubectl delete statefulset pg (default PVC retention)",
       [apply(*pg_base(), pg_sts())], [delete(("statefulset", "pg"))], [P_PG], [SEED_PG]),
    S_(45, "test", "pvc", "kubectl delete pvc data-pg-0 and pod pg-0 (StorageClass reclaimPolicy Delete)",
       [apply(*pg_base(), pg_sts())], [delete(("persistentvolumeclaim", "data-pg-0"), ("pod", "pg-0"))],
       [P_PG], [SEED_PG]),
    S_(46, "test", "pvc", "kubectl delete pvc data-pg-0 and pod pg-0 (StorageClass reclaimPolicy Retain)",
       [apply(*pg_base(), pg_sts(sc="retain"))], [delete(("persistentvolumeclaim", "data-pg-0"), ("pod", "pg-0"))],
       [P_PG], [SEED_PG]),
    S_(47, "test", "auth", "postgres StatefulSet gets POSTGRES_HOST_AUTH_METHOD=trust (data directory already initialized)",
       [apply(*pg_base(), pg_sts())],
       [apply(pg_sts(env_extra=[{"name": "POSTGRES_HOST_AUTH_METHOD", "value": "trust"}]))], [P_PG], [SEED_PG]),
    S_(48, "test", "exposure", "postgres Service ClusterIP -> NodePort",
       [apply(*pg_base(), pg_sts())], [apply(svc("pg", {"app": "pg"}, 5432, typ="NodePort"))], [P_PG], [SEED_PG]),
    S_(49, "test", "data", "postgres Deployment with no volume (data in the container filesystem): env added",
       [apply(*pg_base(), pg_dep("none"))], [apply(pg_dep("none", env_extra=[{"name": "TZ", "value": "UTC"}]))],
       [P_PG], [SEED_PG]),
    S_(50, "test", "data", "postgres Deployment on a PVC, Recreate: env added",
       [apply(*pg_base(), pvc("pg-data"), pg_dep("pvc", strategy=RECREATE))],
       [apply(pg_dep("pvc", strategy=RECREATE, env_extra=[{"name": "TZ", "value": "UTC"}]))], [P_PG], [SEED_PG]),
    S_(51, "test", "pvc", "postgres StatefulSet with PVC retention whenScaled: Delete scaled 1 -> 0",
       [apply(*pg_base(), pg_sts(retention={"whenDeleted": "Retain", "whenScaled": "Delete"}))],
       [apply(pg_sts(replicas=0, retention={"whenDeleted": "Retain", "whenScaled": "Delete"}))], [P_PG], [SEED_PG]),
    S_(52, "test", "pvc", "delete a postgres StatefulSet whose PVC retention is whenDeleted: Retain (explicit)",
       [apply(*pg_base(), pg_sts(retention={"whenDeleted": "Retain", "whenScaled": "Retain"}))],
       [delete(("statefulset", "pg"))], [P_PG], [SEED_PG]),
    S_(53, "test", "data", "redis Deployment with no volume: maxmemory argument added",
       [apply(*rd_base(), rd_dep("none"))], [apply(rd_dep("none", args_extra=["--maxmemory", "64mb"]))],
       [P_RD], [SEED_RD]),
    S_(54, "test", "data", "redis StatefulSet on a PVC, default persistence: image 7 -> 7.4",
       [apply(*rd_base(), rd_sts())], [apply(rd_sts(image=RD_IMG_B))], [P_RD], [SEED_RD]),
    S_(55, "test", "data", "redis StatefulSet on a PVC with --save '' --appendonly yes: env added",
       [apply(*rd_base(), rd_sts(["--save", "", "--appendonly", "yes"]))],
       [apply(rd_sts(["--save", "", "--appendonly", "yes"], env_extra=[{"name": "TZ", "value": "UTC"}]))],
       [P_RD], [SEED_RD]),
    S_(56, "test", "data", "redis StatefulSet on a PVC with --save '' --appendonly no: image 7 -> 7.4",
       [apply(*rd_base(), rd_sts(["--save", "", "--appendonly", "no"]))],
       [apply(rd_sts(["--save", "", "--appendonly", "no"], image=RD_IMG_B))], [P_RD], [SEED_RD]),
    S_(57, "test", "auth", "redis StatefulSet: --requirepass removed from the args",
       [apply(*rd_base(), rd_sts())], [apply(rd_sts(auth=False, probe=False))], [P_RD], [SEED_RD]),
    S_(58, "test", "data", "redis Deployment on emptyDir, default persistence: maxmemory argument added",
       [apply(*rd_base(), rd_dep("emptydir"))], [apply(rd_dep("emptydir", args_extra=["--maxmemory", "64mb"]))],
       [P_RD], [SEED_RD]),
    S_(59, "test", "exposure", "web Service ClusterIP -> LoadBalancer",
       [apply(*web_base(replicas=2))], [apply(svc("web", {"app": "web"}, 80, typ="LoadBalancer"))], [P_WEB]),
    S_(60, "test", "exposure", "hostPort 8088 added to the web pods",
       [apply(*web_base(replicas=1))], [apply(web(replicas=1, host_port=8088))], [P_WEB]),
    S_(61, "test", "exposure", "web Service already NodePort: nodePort 30081 -> 30082",
       [apply(web(replicas=2), svc("web", {"app": "web"}, 80, typ="NodePort", node_port=30081))],
       [apply(svc("web", {"app": "web"}, 80, typ="NodePort", node_port=30082))], [P_WEB]),
    S_(62, "test", "rbac", "RoleBinding of a secret-reading Role to the group of all service accounts of the namespace",
       [apply(*web_base(), role("secret-reader", [{"apiGroups": [""], "resources": ["secrets"],
                                                   "verbs": ["get", "list"]}]))],
       [apply(rolebinding("secret-reader", "secret-reader",
                          [{"kind": "Group", "name": "system:serviceaccounts:@NS@",
                            "apiGroup": "rbac.authorization.k8s.io"}]))], [P_WEB]),
    S_(63, "test", "rbac", "Role on configmaps bound to the default ServiceAccount: verbs [get, list] -> [*]",
       [apply(*web_base(), ROLE_CM, RB_DEFAULT)],
       [apply(role("app-reader", [{"apiGroups": [""], "resources": ["configmaps"], "verbs": ["*"]}]))], [P_WEB]),
    S_(64, "test", "rbac", "ClusterRoleBinding of the built-in 'view' ClusterRole to the namespace default ServiceAccount",
       [apply(*web_base())], [apply(crb("@NS@-view", "view", [sa()]))], [P_WEB]),
    S_(65, "test", "rbac", "Role bound to the default ServiceAccount gains create on pods/exec",
       [apply(*web_base(), ROLE_CM, RB_DEFAULT)],
       [apply(role("app-reader", [{"apiGroups": [""], "resources": ["configmaps"], "verbs": ["get", "list"]},
                                  {"apiGroups": [""], "resources": ["pods", "pods/exec"],
                                   "verbs": ["get", "create"]}]))], [P_WEB]),
    S_(66, "test", "netpol", "NetworkPolicy that limited web to client namespaces is deleted",
       [apply(*web_base(), NP_CLIENTS)], [delete(("networkpolicy", "web-clients"))], [P_WEB]),
    S_(67, "test", "netpol", "NetworkPolicy gains an ingress rule from every namespace (namespaceSelector {})",
       [apply(*web_base(), NP_CLIENTS)],
       [apply(netpol("web-clients", {"matchLabels": {"app": "web"}}, CLIENT_NS + [{"namespaceSelector": {}}]))],
       [P_WEB]),
    S_(68, "test", "helm", "helm upgrade of bitnami/nginx: replicaCount 1 -> 2",
       [helm("web", "nginx", HNG)], [helm("web", "nginx", hv(HNG, replicaCount=2))], [P_HNG]),
    S_(69, "test", "helm", "helm upgrade of bitnami/nginx: service.type NodePort",
       [helm("web", "nginx", HNG)], [helm("web", "nginx", hv(HNG, service__type="NodePort"))], [P_HNG]),
    S_(70, "test", "helm", "helm upgrade of bitnami/postgresql: an extra env var on the primary",
       [helm("db", "postgresql", HPG)],
       [helm("db", "postgresql", hv(HPG, primary__extraEnvVars=[{"name": "TZ", "value": "UTC"}]))],
       [P_HPG], [SEED_HPG]),
    S_(71, "test", "helm", "helm upgrade of bitnami/postgresql: primary.persistence.enabled false",
       [helm("db", "postgresql", HPG)], [helm("db", "postgresql", hv(HPG, primary__persistence__enabled=False))],
       [P_HPG], [SEED_HPG]),
    S_(72, "test", "helm", "helm uninstall of the bitnami/postgresql release",
       [helm("db", "postgresql", HPG)], [{"helm_uninstall": "db"}], [P_HPG], [SEED_HPG]),
    S_(73, "test", "helm", "helm upgrade of bitnami/redis: auth.enabled false",
       [helm("rd", "redis", HRD)], [helm("rd", "redis", hv(HRD, auth__enabled=False))], [P_HRD], [SEED_HRD]),
    S_(74, "test", "helm", "helm upgrade of bitnami/redis: master.persistence.enabled false",
       [helm("rd", "redis", HRD)], [helm("rd", "redis", hv(HRD, master__persistence__enabled=False))],
       [P_HRD], [SEED_HRD]),
    S_(75, "test", "helm", "helm upgrade of bitnami/postgresql: fullnameOverride set to 'maindb'",
       [helm("db", "postgresql", HPG)], [helm("db", "postgresql", hv(HPG, fullnameOverride="maindb"))],
       [P_HPG], [SEED_HPG]),
]
BY_ID = {s["id"]: s for s in S}
