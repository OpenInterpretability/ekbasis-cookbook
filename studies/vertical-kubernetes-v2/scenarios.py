"""Kubernetes change scenarios for the v2 study. NONE of them is a v1 scenario (the 75 v1 scenarios are development
material only).

Origin of each scenario (field `origin`):
  real-upgrade  a real chart, installed at one released version and upgraded with `helm upgrade` to the next release
                whose image changes (same values); chart archives pulled unmodified into charts/src.
  real-values   a real chart (released version) with a values change that its own values.yaml documents.
  real-uninstall  `helm uninstall` of a real chart release.
  real-docs     manifests and changes taken from the kubernetes.io documentation examples (content/en/examples) or
                commands from the docs pages; adaptations are listed in `adapted` (e.g. a probe Service added, a
                hostPath made per-namespace, an amd64-only image replaced).
  written       written by us (Claude, this session) to cover a mechanism.

Real charts (charts/src, pulled from their public repos):
  podinfo (stefanprodan/podinfo), groundhog2k postgres / redis / mariadb (official docker images), grafana/grafana,
  bitnami postgresql / redis (OCI bitnamicharts; images from docker.io/bitnamilegacy, the repository Bitnami moved
  its versioned images to in 2025, with global.security.allowInsecureImages true, as the charts require for that).

Each scenario runs in its own namespace s<id> of the local kind cluster vk8s2:
  v1     steps that build the starting point;  seed: data written after v1;  probes: client endpoints;
  v2     the change under test.   locks: named locks (a scenario touching cluster-wide state runs alone).
Expected outcomes are NOT stored here: labels come only from execution (runner.py).
split: "dev" (used to build the state, the notes and the rich rule) or "test" (frozen by hash before labelling).
"""
from __future__ import annotations

import copy

PG_PW = "pgpass-5e2a"          # throwaway credentials of the local cluster, never shown to the model
RD_PW = "rdpass-08c3"
MY_PW = "mypass-77d1"
GF_PW = "gfpass-c41b"

LEGACY = {"global": {"security": {"allowInsecureImages": True}}}


def deep(base, **patch):
    """Copy of base with a__b__c=v set (dict path)."""
    out = copy.deepcopy(base)
    for path, v in patch.items():
        cur = out
        ks = path.split("__")
        for k in ks[:-1]:
            cur = cur.setdefault(k, {})
        cur[ks[-1]] = v
    return out


def mod(obj, fn):
    o = copy.deepcopy(obj)
    fn(o)
    return o


def merge(a, b):
    out = copy.deepcopy(a)
    for k, v in b.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


# ---------------------------------------------------------------- steps

def apply(*objs):
    return {"apply": list(objs)}


def delete(*refs):
    return {"delete": list(refs)}


def helm(release, chart, values):
    return {"helm": {"release": release, "chart": chart, "values": values}}


def uninstall(release):
    return {"helm_uninstall": release}


# ---------------------------------------------------------------- probes and seeds

def p_http(host, port=80, path="/", name=None):
    return {"name": name or host, "type": "http", "host": host, "port": port, "path": path}


def p_tcp(host, port, name=None):
    return {"name": name or host, "type": "tcp", "host": host, "port": port}


def p_pg(host, user, db, pw=PG_PW):
    return {"name": host, "type": "pg", "host": host, "port": 5432, "user": user, "password": pw, "db": db}


def p_redis(host, pw=None):
    return {"name": host, "type": "redis", "host": host, "port": 6379, "password": pw}


def p_mysql(host, user="root", pw=MY_PW, db="appdb"):
    return {"name": host, "type": "mysql", "host": host, "port": 3306, "user": user, "password": pw, "db": db}


def s_pg(pod, user, db, pw=PG_PW):
    return {"op": "pg", "pod": pod, "user": user, "password": pw, "db": db}


def s_redis(pod, pw=None):
    return {"op": "redis", "pod": pod, "password": pw}


def s_mysql(pod, user="root", pw=MY_PW, db="appdb"):
    return {"op": "mysql", "pod": pod, "user": user, "password": pw, "db": db}


def s_grafana(host, pod, pw=GF_PW):
    return {"op": "grafana", "host": host, "pod": pod, "password": pw}


# ---------------------------------------------------------------- real charts: base values

PODINFO = {}                                     # chart defaults: 1 replica, RollingUpdate maxUnavailable 1
PODINFO2 = {"replicaCount": 2}
PODINFO3 = {"replicaCount": 3}
GP = {"settings": {"superuserPassword": {"value": PG_PW}}}            # groundhog2k/postgres defaults (emptyDir)
GPS = merge(GP, {"storage": {"requestedSize": "1Gi"}})                # ... with a PVC from volumeClaimTemplates
GR = {}                                                                # groundhog2k/redis defaults (emptyDir, no password)
GRS = {"storage": {"requestedSize": "1Gi"}}
GM = {"settings": {"rootPassword": {"value": MY_PW}}}                 # groundhog2k/mariadb defaults (emptyDir)
GMS = merge(GM, {"storage": {"requestedSize": "1Gi"}})
GF = {"adminPassword": GF_PW}                                          # grafana defaults (no persistence)
GFS = merge(GF, {"persistence": {"enabled": True, "size": "1Gi"}})
BPG = merge(LEGACY, {"image": {"repository": "bitnamilegacy/postgresql"},
                     "auth": {"username": "app", "password": PG_PW, "database": "appdb",
                              "postgresPassword": PG_PW + "-admin"},
                     "primary": {"persistence": {"size": "1Gi"}, "resourcesPreset": "small"}})
BRD = merge(LEGACY, {"image": {"repository": "bitnamilegacy/redis"}, "architecture": "standalone",
                     "auth": {"password": RD_PW},
                     "master": {"persistence": {"size": "1Gi"}, "resourcesPreset": "small"}})

P_PODINFO = p_http("web-podinfo", 9898)
P_GP, S_GP = p_pg("db-postgres", "postgres", "postgres"), s_pg("app.kubernetes.io/instance=db", "postgres", "postgres")
P_GR, S_GR = p_redis("cache-redis"), s_redis("app.kubernetes.io/instance=cache")
P_GM, S_GM = p_mysql("maria-mariadb"), s_mysql("app.kubernetes.io/instance=maria")
P_GF, S_GF = p_http("graf-grafana", 80, "/api/health"), s_grafana("graf-grafana", "app.kubernetes.io/instance=graf")
P_BPG, S_BPG = (p_pg("bdb-postgresql", "app", "appdb"), s_pg("app.kubernetes.io/instance=bdb", "app", "appdb"))
P_BRD, S_BRD = p_redis("brd-redis-master", RD_PW), s_redis("app.kubernetes.io/instance=brd", RD_PW)


# ---------------------------------------------------------------- kubernetes.io docs examples (content/en/examples)

def docs_nginx_deployment(replicas=2, image="nginx:1.14.2", name="nginx-deployment"):
    """application/deployment.yaml (2 replicas), controllers/nginx-deployment.yaml (3 replicas, labels app: nginx)."""
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name, "labels": {"app": "nginx"}},
            "spec": {"replicas": replicas, "selector": {"matchLabels": {"app": "nginx"}},
                     "template": {"metadata": {"labels": {"app": "nginx"}},
                                  "spec": {"containers": [{"name": "nginx", "image": image,
                                                           "ports": [{"containerPort": 80}]}]}}}}


def svc(name, selector, port, target=None, typ="ClusterIP", headless=False, port_name=None, node_port=None):
    p = {"port": port, "targetPort": target if target is not None else port, "protocol": "TCP"}
    if port_name:
        p["name"] = port_name
    if node_port:
        p["nodePort"] = node_port
    spec = {"selector": selector, "ports": [p]}
    if headless:
        spec["clusterIP"] = "None"
    else:
        spec["type"] = typ
    return {"apiVersion": "v1", "kind": "Service", "metadata": {"name": name}, "spec": spec}


def docs_mysql(env_pw="password", image="mysql:9"):
    """application/mysql/mysql-deployment.yaml (Service headless + Deployment Recreate, root password in env)."""
    return [{"apiVersion": "v1", "kind": "Service", "metadata": {"name": "mysql"},
             "spec": {"ports": [{"port": 3306}], "selector": {"app": "mysql"}, "clusterIP": "None"}},
            {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "mysql"},
             "spec": {"selector": {"matchLabels": {"app": "mysql"}}, "strategy": {"type": "Recreate"},
                      "template": {"metadata": {"labels": {"app": "mysql"}},
                                   "spec": {"containers": [{"image": image, "name": "mysql",
                                                            "env": [{"name": "MYSQL_ROOT_PASSWORD", "value": env_pw}],
                                                            "ports": [{"containerPort": 3306, "name": "mysql"}],
                                                            "volumeMounts": [{"name": "mysql-persistent-storage",
                                                                              "mountPath": "/var/lib/mysql"}]}],
                                            "volumes": [{"name": "mysql-persistent-storage",
                                                         "persistentVolumeClaim": {"claimName": "mysql-pv-claim"}}]}}}}]


def docs_mysql_pv():
    """application/mysql/mysql-pv.yaml (hostPath PV, storageClassName manual). Adapted: the hostPath and the PV name
    are per namespace, and the PV is pre-bound to the claim, so parallel scenarios cannot share it."""
    return [{"apiVersion": "v1", "kind": "PersistentVolume",
             "metadata": {"name": "mysql-pv-volume-@NS@", "labels": {"type": "local"}},
             "spec": {"storageClassName": "manual", "capacity": {"storage": "20Gi"}, "accessModes": ["ReadWriteOnce"],
                      "hostPath": {"path": "/mnt/vk/@NS@/data"},
                      "claimRef": {"namespace": "@NS@", "name": "mysql-pv-claim"}}},
            {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": "mysql-pv-claim"},
             "spec": {"storageClassName": "manual", "accessModes": ["ReadWriteOnce"],
                      "resources": {"requests": {"storage": "20Gi"}}}}]


def docs_wp_mysql(image="mysql:8.0"):
    """application/wordpress/mysql-deployment.yaml; the Secret mysql-pass comes from the kustomization's
    secretGenerator (here a plain Secret)."""
    return [{"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "mysql-pass"}, "type": "Opaque",
             "stringData": {"password": MY_PW}},
            {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "wordpress-mysql", "labels": {"app": "wordpress"}},
             "spec": {"ports": [{"port": 3306}], "selector": {"app": "wordpress", "tier": "mysql"}, "clusterIP": "None"}},
            {"apiVersion": "v1", "kind": "PersistentVolumeClaim",
             "metadata": {"name": "mysql-pv-claim", "labels": {"app": "wordpress"}},
             "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "20Gi"}}}},
            {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "wordpress-mysql", "labels": {"app": "wordpress"}},
             "spec": {"selector": {"matchLabels": {"app": "wordpress", "tier": "mysql"}}, "strategy": {"type": "Recreate"},
                      "template": {"metadata": {"labels": {"app": "wordpress", "tier": "mysql"}},
                                   "spec": {"containers": [{
                                       "image": image, "name": "mysql",
                                       "env": [{"name": "MYSQL_ROOT_PASSWORD",
                                                "valueFrom": {"secretKeyRef": {"name": "mysql-pass", "key": "password"}}},
                                               {"name": "MYSQL_DATABASE", "value": "wordpress"},
                                               {"name": "MYSQL_USER", "value": "wordpress"},
                                               {"name": "MYSQL_PASSWORD",
                                                "valueFrom": {"secretKeyRef": {"name": "mysql-pass", "key": "password"}}}],
                                       "ports": [{"containerPort": 3306, "name": "mysql"}],
                                       "volumeMounts": [{"name": "mysql-persistent-storage", "mountPath": "/var/lib/mysql"}]}],
                                       "volumes": [{"name": "mysql-persistent-storage",
                                                    "persistentVolumeClaim": {"claimName": "mysql-pv-claim"}}]}}}}]


def docs_redis_leader(image="docker.io/redis:6.0.5", resources=None):
    """application/guestbook/redis-leader-deployment.yaml + service. Adapted: the image is docker.io/redis:6.0.5, the
    one the guestbook used before the docs switched to an amd64-only registry.k8s.io digest."""
    res = resources or {"requests": {"cpu": "100m", "memory": "100Mi"}}
    return [{"apiVersion": "apps/v1", "kind": "Deployment",
             "metadata": {"name": "redis-leader", "labels": {"app": "redis", "role": "leader", "tier": "backend"}},
             "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "redis"}},
                      "template": {"metadata": {"labels": {"app": "redis", "role": "leader", "tier": "backend"}},
                                   "spec": {"containers": [{"name": "leader", "image": image, "resources": res,
                                                            "ports": [{"containerPort": 6379}]}]}}}},
            {"apiVersion": "v1", "kind": "Service",
             "metadata": {"name": "redis-leader", "labels": {"app": "redis", "role": "leader", "tier": "backend"}},
             "spec": {"ports": [{"port": 6379, "targetPort": 6379}],
                      "selector": {"app": "redis", "role": "leader", "tier": "backend"}}}]


def docs_web_sts(image="nginx:1.26-alpine", replicas=2, partition=None):
    """application/web/web.yaml (StatefulSet tutorial). Adapted: nginx-slim (amd64 only) replaced by nginx alpine;
    a ClusterIP Service 'web' added for the probe (the tutorial's Service is headless)."""
    spec = {"serviceName": "nginx", "replicas": replicas, "selector": {"matchLabels": {"app": "nginx"}},
            "template": {"metadata": {"labels": {"app": "nginx"}},
                         "spec": {"containers": [{"name": "nginx", "image": image,
                                                  "ports": [{"containerPort": 80, "name": "web"}],
                                                  "volumeMounts": [{"name": "www", "mountPath": "/usr/share/nginx/html"}]}]}},
            "volumeClaimTemplates": [{"metadata": {"name": "www"},
                                      "spec": {"accessModes": ["ReadWriteOnce"],
                                               "resources": {"requests": {"storage": "1Gi"}}}}]}
    if partition is not None:
        spec["updateStrategy"] = {"type": "RollingUpdate", "rollingUpdate": {"partition": partition}}
    return {"apiVersion": "apps/v1", "kind": "StatefulSet", "metadata": {"name": "web"}, "spec": spec}


DOCS_WEB_SVC = [{"apiVersion": "v1", "kind": "Service", "metadata": {"name": "nginx", "labels": {"app": "nginx"}},
                 "spec": {"ports": [{"port": 80, "name": "web"}], "clusterIP": "None", "selector": {"app": "nginx"}}},
                svc("web", {"app": "nginx"}, 80)]

NP_DEFAULT_DENY = {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
                   "metadata": {"name": "default-deny-ingress"},
                   "spec": {"podSelector": {}, "policyTypes": ["Ingress"]}}
NP_ALLOW_ALL = {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "allow-all-ingress"},
                "spec": {"podSelector": {}, "ingress": [{}], "policyTypes": ["Ingress"]}}


def np_from_ns(name, pod_sel, ns_labels):
    return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": name},
            "spec": {"podSelector": {"matchLabels": pod_sel}, "policyTypes": ["Ingress"],
                     "ingress": [{"from": [{"namespaceSelector": ({"matchLabels": ns_labels} if ns_labels is not None
                                                                  else {})}]}]}}


def rolebinding(name, role_kind, role_name, subjects):
    return {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding", "metadata": {"name": name},
            "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": role_kind, "name": role_name},
            "subjects": subjects}


def crb(name, role_name, subjects):
    return {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding", "metadata": {"name": name},
            "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": role_name},
            "subjects": subjects}


SECRET_READER_CR = {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole",
                    "metadata": {"name": "secret-reader-@NS@"},
                    "rules": [{"apiGroups": [""], "resources": ["secrets"], "verbs": ["get", "watch", "list"]}]}
G_SA_NS = {"kind": "Group", "name": "system:serviceaccounts:@NS@", "apiGroup": "rbac.authorization.k8s.io"}
G_SA_ALL = {"kind": "Group", "name": "system:serviceaccounts", "apiGroup": "rbac.authorization.k8s.io"}
U_DAVE = {"kind": "User", "name": "dave", "apiGroup": "rbac.authorization.k8s.io"}
SA_DEFAULT = {"kind": "ServiceAccount", "name": "default", "namespace": "@NS@"}
APP_SECRET = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "app-credentials"}, "type": "Opaque",
              "stringData": {"token": "t-123"}}


# ---------------------------------------------------------------- written workloads (ours)

def web(name="web", replicas=2, image="nginx:1.26-alpine", probe=True, strategy=None, port_name=None, labels=None):
    lab = {"app": name}
    c = {"name": "nginx", "image": image, "ports": [{"containerPort": 80}]}
    if port_name:
        c["ports"][0]["name"] = port_name
    if probe:
        c["readinessProbe"] = {"httpGet": {"path": "/", "port": 80}, "periodSeconds": 1, "failureThreshold": 2}
    spec = {"replicas": replicas, "selector": {"matchLabels": lab},
            "template": {"metadata": {"labels": dict(lab, **(labels or {}))},
                         "spec": {"containers": [c], "terminationGracePeriodSeconds": 10}}}
    if strategy:
        spec["strategy"] = strategy
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name}, "spec": spec}


def pg_container(image="postgres:17-alpine", env_extra=None):
    return {"name": "postgres", "image": image, "ports": [{"containerPort": 5432}],
            "env": [{"name": "POSTGRES_USER", "value": "app"}, {"name": "POSTGRES_DB", "value": "appdb"},
                    {"name": "POSTGRES_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "pg-secret", "key": "password"}}}]
                   + (env_extra or []),
            "readinessProbe": {"exec": {"command": ["pg_isready", "-U", "app", "-d", "appdb"]}, "periodSeconds": 1,
                               "failureThreshold": 2},
            "volumeMounts": [{"name": "data", "mountPath": "/var/lib/postgresql/data"}]}


def pg_sts(retention=None, replicas=1, sc="standard"):
    spec = {"serviceName": "pg", "replicas": replicas, "selector": {"matchLabels": {"app": "pg"}},
            "template": {"metadata": {"labels": {"app": "pg"}},
                         "spec": {"terminationGracePeriodSeconds": 20, "containers": [pg_container()]}},
            "volumeClaimTemplates": [{"metadata": {"name": "data"},
                                      "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": sc,
                                               "resources": {"requests": {"storage": "1Gi"}}}}]}
    if retention:
        spec["persistentVolumeClaimRetentionPolicy"] = retention
    return {"apiVersion": "apps/v1", "kind": "StatefulSet", "metadata": {"name": "pg"}, "spec": spec}


def pg_dep_pvc(image="postgres:17-alpine", claim="pg-data"):
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "pg"},
            "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "pg"}}, "strategy": {"type": "Recreate"},
                     "template": {"metadata": {"labels": {"app": "pg"}},
                                  "spec": {"terminationGracePeriodSeconds": 20, "containers": [pg_container(image)],
                                           "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": claim}}]}}}}


def pvc(name, sc="standard"):
    return {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": name},
            "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": sc,
                     "resources": {"requests": {"storage": "1Gi"}}}}


PG_SECRET = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "pg-secret"}, "type": "Opaque",
             "stringData": {"password": PG_PW}}
P_PG = p_pg("pg", "app", "appdb")
S_PG = s_pg("app=pg", "app", "appdb")


def rd_sts(args):
    c = {"name": "redis", "image": "redis:7-alpine", "args": ["--requirepass", "$(REDIS_PASSWORD)"] + args,
         "ports": [{"containerPort": 6379}],
         "env": [{"name": "REDIS_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "rd-secret", "key": "password"}}}],
         "volumeMounts": [{"name": "data", "mountPath": "/data"}]}
    return {"apiVersion": "apps/v1", "kind": "StatefulSet", "metadata": {"name": "redis"},
            "spec": {"serviceName": "redis", "replicas": 1, "selector": {"matchLabels": {"app": "redis"}},
                     "template": {"metadata": {"labels": {"app": "redis"}},
                                  "spec": {"terminationGracePeriodSeconds": 20, "containers": [c]}},
                     "volumeClaimTemplates": [{"metadata": {"name": "data"},
                                               "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": "standard",
                                                        "resources": {"requests": {"storage": "1Gi"}}}}]}}


RD_SECRET = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "rd-secret"}, "type": "Opaque",
             "stringData": {"password": RD_PW}}


# ---------------------------------------------------------------- scenarios

def S_(i, split, origin, title, v1, v2, probes, seed=(), adapted=None, locks=()):
    return {"id": i, "split": split, "origin": origin, "title": title, "v1": v1, "v2": v2, "probes": probes,
            "seed": list(seed), "adapted": adapted, "locks": list(locks)}


GLOBAL = "global"              # exclusive: changes cluster-wide RBAC, so nothing else may run meanwhile
NODEPORT = "nodeport-31198"     # podinfo's fixed nodePort

S = [
    # ============================================================ DEV
    S_(1, "dev", "real-upgrade", "podinfo 6.8.0 -> 6.9.4, chart defaults (1 replica)",
       [helm("web", "podinfo-6.8.0", PODINFO)], [helm("web", "podinfo-6.9.4", PODINFO)], [P_PODINFO]),
    S_(2, "dev", "real-values", "podinfo 6.15.0, 2 replicas: service.type LoadBalancer",
       [helm("web", "podinfo-6.15.0", PODINFO2)],
       [helm("web", "podinfo-6.15.0", merge(PODINFO2, {"service": {"type": "LoadBalancer"}}))], [P_PODINFO],
       locks=[NODEPORT]),
    S_(3, "dev", "real-upgrade", "groundhog2k/postgres 1.4.11 -> 1.4.12 with a PVC (postgres 16.13 -> 16.14)",
       [helm("db", "postgres-1.4.11", GPS)], [helm("db", "postgres-1.4.12", GPS)], [P_GP], [S_GP]),
    S_(4, "dev", "real-values", "groundhog2k/postgres 1.5.14 defaults (no PVC): an extra env var",
       [helm("db", "postgres-1.5.14", GP)],
       [helm("db", "postgres-1.5.14", merge(GP, {"env": [{"name": "TZ", "value": "UTC"}]}))], [P_GP], [S_GP]),
    S_(5, "dev", "real-upgrade", "groundhog2k/redis 2.4.7 -> 2.4.8 with a PVC and keepPvc",
       [helm("cache", "redis-2.4.7", merge(GRS, {"storage": {"keepPvc": True}}))],
       [helm("cache", "redis-2.4.8", merge(GRS, {"storage": {"keepPvc": True}}))], [P_GR], [S_GR]),
    S_(6, "dev", "real-uninstall", "helm uninstall of groundhog2k/redis 2.4.8 with chart defaults (no PVC)",
       [helm("cache", "redis-2.4.8", GR)], [uninstall("cache")], [P_GR], [S_GR]),
    S_(7, "dev", "real-uninstall", "helm uninstall of groundhog2k/mariadb 4.4.9 with a PVC",
       [helm("maria", "mariadb-4.4.9", GMS)], [uninstall("maria")], [P_GM], [S_GM]),
    S_(8, "dev", "real-values", "grafana chart 10.5.15 defaults (no persistence): env var added",
       [helm("graf", "grafana-10.5.15", GF)],
       [helm("graf", "grafana-10.5.15", merge(GF, {"env": {"GF_LOG_LEVEL": "warn"}}))], [P_GF], [S_GF]),
    S_(9, "dev", "real-values", "bitnami/postgresql 16.7.27: fullnameOverride 'maindb'",
       [helm("bdb", "postgresql-16.7.27", BPG)], [helm("bdb", "postgresql-16.7.27", merge(BPG, {"fullnameOverride": "maindb"}))],
       [P_BPG], [S_BPG]),
    S_(10, "dev", "real-values", "bitnami/redis 21.2.7: master.persistence.enabled false",
       [helm("brd", "redis-21.2.7", BRD)],
       [helm("brd", "redis-21.2.7", merge(BRD, {"master": {"persistence": {"enabled": False}}}))], [P_BRD], [S_BRD]),
    S_(11, "dev", "real-docs", "docs nginx-deployment (3 replicas): kubectl scale to 1",
       [apply(docs_nginx_deployment(3), svc("nginx", {"app": "nginx"}, 80))],
       [apply(docs_nginx_deployment(1))], [p_http("nginx")], adapted="probe Service added"),
    S_(12, "dev", "real-docs", "docs NetworkPolicy allowing only labelled client namespaces added to a web app",
       [apply(web(), svc("web", {"app": "web"}, 80))],
       [apply(np_from_ns("web-clients", {"app": "web"}, {"role": "client"}))], [p_http("web")],
       adapted="written workload; the policy follows the docs' namespaceSelector example"),
    S_(13, "dev", "real-docs", "docs mysql single-instance: MYSQL_ROOT_PASSWORD value changed in the manifest",
       [apply(*docs_mysql_pv(), *docs_mysql("password"))], [apply(*docs_mysql("newpassword"))],
       [p_mysql("mysql", pw="password")], [s_mysql("app=mysql", pw="password")],
       adapted="hostPath and PV name per namespace, PV pre-bound"),
    S_(14, "dev", "real-docs", "docs RBAC: rolebinding default-view (ClusterRole view) for the default ServiceAccount",
       [apply(web(), svc("web", {"app": "web"}, 80), APP_SECRET)],
       [apply(rolebinding("default-view", "ClusterRole", "view", [SA_DEFAULT]))], [p_http("web")],
       adapted="written workload"),
    S_(15, "dev", "written", "Service port 80 -> 8080 (targetPort 80 kept); clients still use 80",
       [apply(web(), svc("web", {"app": "web"}, 80))], [apply(svc("web", {"app": "web"}, 8080, target=80))],
       [p_http("web")]),
    S_(16, "dev", "written", "postgres StatefulSet, 1 replica, readiness probe, PVC: env added",
       [apply(PG_SECRET, svc("pg", {"app": "pg"}, 5432), pg_sts())],
       [apply(mod(pg_sts(), lambda o: o["spec"]["template"]["spec"]["containers"][0]["env"].append(
           {"name": "TZ", "value": "UTC"})))], [P_PG], [S_PG]),
    S_(17, "dev", "written", "web Deployment, 1 replica, no probe, command sleeps 8 s before nginx: image bump",
       [apply(mod(web(replicas=1, probe=False), lambda o: o["spec"]["template"]["spec"]["containers"][0].update(
           command=["sh", "-c", "sleep 8; exec nginx -g 'daemon off;'"])), svc("web", {"app": "web"}, 80))],
       [apply(mod(web(replicas=1, probe=False, image="nginx:1.27-alpine"),
                  lambda o: o["spec"]["template"]["spec"]["containers"][0].update(
                      command=["sh", "-c", "sleep 8; exec nginx -g 'daemon off;'"])))], [p_http("web")]),
    S_(18, "dev", "written", "redis StatefulSet on a PVC with --save '' --appendonly no: pod template env added",
       [apply(RD_SECRET, svc("redis", {"app": "redis"}, 6379), rd_sts(["--save", "", "--appendonly", "no"]))],
       [apply(mod(rd_sts(["--save", "", "--appendonly", "no"]), lambda o: o["spec"]["template"]["spec"]["containers"][0][
           "env"].append({"name": "TZ", "value": "UTC"})))],
       [p_redis("redis", RD_PW)], [s_redis("app=redis", RD_PW)]),
    S_(19, "dev", "real-values", "groundhog2k/mariadb 4.4.9 with a PVC: service.type NodePort",
       [helm("maria", "mariadb-4.4.9", GMS)],
       [helm("maria", "mariadb-4.4.9", merge(GMS, {"service": {"type": "NodePort"}}))], [P_GM], [S_GM]),
    S_(20, "dev", "real-values", "podinfo 6.15.0 defaults: service.hostPort 8098",
       [helm("web", "podinfo-6.15.0", PODINFO)],
       [helm("web", "podinfo-6.15.0", {"service": {"hostPort": 8098}})], [P_PODINFO], locks=["hostport-8098"]),

    # ============================================================ TEST
    # ---- podinfo
    S_(21, "test", "real-upgrade", "podinfo 6.9.4 -> 6.10.0, chart defaults (1 replica)",
       [helm("web", "podinfo-6.9.4", PODINFO)], [helm("web", "podinfo-6.10.0", PODINFO)], [P_PODINFO]),
    S_(22, "test", "real-upgrade", "podinfo 6.7.1 -> 6.8.0, replicaCount 2",
       [helm("web", "podinfo-6.7.1", PODINFO2)], [helm("web", "podinfo-6.8.0", PODINFO2)], [P_PODINFO]),
    S_(23, "test", "real-upgrade", "podinfo 6.14.1 -> 6.15.0, replicaCount 3",
       [helm("web", "podinfo-6.14.1", PODINFO3)], [helm("web", "podinfo-6.15.0", PODINFO3)], [P_PODINFO]),
    S_(24, "test", "real-values", "podinfo 6.15.0, 2 replicas: service.type NodePort",
       [helm("web", "podinfo-6.15.0", PODINFO2)],
       [helm("web", "podinfo-6.15.0", merge(PODINFO2, {"service": {"type": "NodePort"}}))], [P_PODINFO],
       locks=[NODEPORT]),
    S_(25, "test", "real-values", "podinfo 6.15.0: replicaCount 2 -> 3",
       [helm("web", "podinfo-6.15.0", PODINFO2)], [helm("web", "podinfo-6.15.0", PODINFO3)], [P_PODINFO]),
    S_(26, "test", "real-values", "podinfo 6.15.0, 2 replicas: ui.color changed",
       [helm("web", "podinfo-6.15.0", PODINFO2)],
       [helm("web", "podinfo-6.15.0", merge(PODINFO2, {"ui": {"color": "#aa3300"}}))], [P_PODINFO]),
    S_(27, "test", "real-values", "podinfo 6.15.0, 2 replicas: service.hostPort 8099",
       [helm("web", "podinfo-6.15.0", PODINFO2)],
       [helm("web", "podinfo-6.15.0", merge(PODINFO2, {"service": {"hostPort": 8099}}))], [P_PODINFO],
       locks=["hostport-8099"]),
    S_(28, "test", "real-values", "podinfo 6.15.0, 2 replicas: image.tag '6.15' (a tag that does not exist)",
       [helm("web", "podinfo-6.15.0", PODINFO2)],
       [helm("web", "podinfo-6.15.0", merge(PODINFO2, {"image": {"tag": "6.15"}}))], [P_PODINFO]),
    S_(29, "test", "real-uninstall", "helm uninstall of podinfo 6.15.0 (2 replicas)",
       [helm("web", "podinfo-6.15.0", PODINFO2)], [uninstall("web")], [P_PODINFO]),
    S_(30, "test", "real-values", "podinfo 6.15.0 defaults (1 replica): podAnnotations added",
       [helm("web", "podinfo-6.15.0", PODINFO)],
       [helm("web", "podinfo-6.15.0", {"podAnnotations": {"team": "payments"}})], [P_PODINFO]),
    # ---- groundhog2k/postgres
    S_(31, "test", "real-upgrade", "groundhog2k/postgres 1.5.13 -> 1.5.14, chart defaults (no PVC)",
       [helm("db", "postgres-1.5.13", GP)], [helm("db", "postgres-1.5.14", GP)], [P_GP], [S_GP]),
    S_(32, "test", "real-upgrade", "groundhog2k/postgres 1.5.13 -> 1.5.14 with a PVC",
       [helm("db", "postgres-1.5.13", GPS)], [helm("db", "postgres-1.5.14", GPS)], [P_GP], [S_GP]),
    S_(33, "test", "real-upgrade", "groundhog2k/postgres 1.5.14 -> 1.6.1 with a PVC (postgres 17 -> 18)",
       [helm("db", "postgres-1.5.14", GPS)], [helm("db", "postgres-1.6.1", GPS)], [P_GP], [S_GP]),
    S_(34, "test", "real-values", "groundhog2k/postgres 1.5.14 installed without a PVC: storage.requestedSize 1Gi added",
       [helm("db", "postgres-1.5.14", GP)], [helm("db", "postgres-1.5.14", GPS)], [P_GP], [S_GP]),
    S_(35, "test", "real-values", "groundhog2k/postgres 1.5.14 with a PVC: service.type NodePort",
       [helm("db", "postgres-1.5.14", GPS)],
       [helm("db", "postgres-1.5.14", merge(GPS, {"service": {"type": "NodePort"}}))], [P_GP], [S_GP]),
    S_(36, "test", "real-uninstall", "helm uninstall of groundhog2k/postgres 1.5.14 with a PVC",
       [helm("db", "postgres-1.5.14", GPS)], [uninstall("db")], [P_GP], [S_GP]),
    S_(37, "test", "real-uninstall", "helm uninstall of groundhog2k/postgres 1.5.14, chart defaults (no PVC)",
       [helm("db", "postgres-1.5.14", GP)], [uninstall("db")], [P_GP], [S_GP]),
    S_(38, "test", "real-values", "groundhog2k/postgres 1.5.14 with a PVC: resources.limits.memory 512Mi",
       [helm("db", "postgres-1.5.14", GPS)],
       [helm("db", "postgres-1.5.14", merge(GPS, {"resources": {"limits": {"memory": "512Mi"}}}))], [P_GP], [S_GP]),
    S_(39, "test", "real-values", "groundhog2k/postgres 1.5.14 with a PVC: settings.superuserPassword changed",
       [helm("db", "postgres-1.5.14", GPS)],
       [helm("db", "postgres-1.5.14", merge(GPS, {"settings": {"superuserPassword": {"value": "rotated-9f2"}}}))],
       [P_GP], [S_GP]),
    S_(40, "test", "real-values", "groundhog2k/postgres 1.5.14 with a PVC: service.annotations added",
       [helm("db", "postgres-1.5.14", GPS)],
       [helm("db", "postgres-1.5.14", merge(GPS, {"service": {"annotations": {"team": "data"}}}))], [P_GP], [S_GP]),
    # ---- groundhog2k/redis
    S_(41, "test", "real-upgrade", "groundhog2k/redis 2.4.7 -> 2.4.8, chart defaults (no PVC)",
       [helm("cache", "redis-2.4.7", GR)], [helm("cache", "redis-2.4.8", GR)], [P_GR], [S_GR]),
    S_(42, "test", "real-upgrade", "groundhog2k/redis 2.4.7 -> 2.4.8 with a PVC",
       [helm("cache", "redis-2.4.7", GRS)], [helm("cache", "redis-2.4.8", GRS)], [P_GR], [S_GR]),
    S_(43, "test", "real-upgrade", "groundhog2k/redis 2.3.4 -> 2.4.4 with a PVC (redis 8.6 -> 8.8)",
       [helm("cache", "redis-2.3.4", GRS)], [helm("cache", "redis-2.4.4", GRS)], [P_GR], [S_GR]),
    S_(44, "test", "real-upgrade", "groundhog2k/redis 1.3.11 -> 2.0.0 with a PVC (chart major; redis 7.4 -> 8.0)",
       [helm("cache", "redis-1.3.11", GRS)], [helm("cache", "redis-2.0.0", GRS)], [P_GR], [S_GR]),
    S_(45, "test", "real-uninstall", "helm uninstall of groundhog2k/redis 2.4.8 with a PVC",
       [helm("cache", "redis-2.4.8", GRS)], [uninstall("cache")], [P_GR], [S_GR]),
    S_(46, "test", "real-uninstall", "helm uninstall of groundhog2k/redis 2.4.8 with a PVC and storage.keepPvc true",
       [helm("cache", "redis-2.4.8", merge(GRS, {"storage": {"keepPvc": True}}))], [uninstall("cache")], [P_GR], [S_GR]),
    S_(47, "test", "real-values", "groundhog2k/redis 2.4.8 installed without a PVC: storage.requestedSize 1Gi added",
       [helm("cache", "redis-2.4.8", GR)], [helm("cache", "redis-2.4.8", GRS)], [P_GR], [S_GR]),
    # ---- groundhog2k/mariadb
    S_(48, "test", "real-upgrade", "groundhog2k/mariadb 4.4.8 -> 4.4.9 with a PVC",
       [helm("maria", "mariadb-4.4.8", GMS)], [helm("maria", "mariadb-4.4.9", GMS)], [P_GM], [S_GM]),
    S_(49, "test", "real-upgrade", "groundhog2k/mariadb 4.4.8 -> 4.4.9, chart defaults (no PVC)",
       [helm("maria", "mariadb-4.4.8", GM)], [helm("maria", "mariadb-4.4.9", GM)], [P_GM], [S_GM]),
    S_(50, "test", "real-upgrade", "groundhog2k/mariadb 4.3.7 -> 4.4.1 with a PVC (mariadb 11.4 -> 11.8)",
       [helm("maria", "mariadb-4.3.7", GMS)], [helm("maria", "mariadb-4.4.1", GMS)], [P_GM], [S_GM]),
    S_(51, "test", "real-values", "groundhog2k/mariadb 4.4.9 with a PVC: settings.rootPassword changed",
       [helm("maria", "mariadb-4.4.9", GMS)],
       [helm("maria", "mariadb-4.4.9", merge(GMS, {"settings": {"rootPassword": {"value": "rotated-3c1"}}}))],
       [P_GM], [S_GM]),
    # ---- grafana
    S_(52, "test", "real-upgrade", "grafana chart 10.1.4 -> 10.4.0, chart defaults (no persistence)",
       [helm("graf", "grafana-10.1.4", GF)], [helm("graf", "grafana-10.4.0", GF)], [P_GF], [S_GF]),
    S_(53, "test", "real-upgrade", "grafana chart 10.1.4 -> 10.4.0 with persistence",
       [helm("graf", "grafana-10.1.4", GFS)], [helm("graf", "grafana-10.4.0", GFS)], [P_GF], [S_GF]),
    S_(54, "test", "real-upgrade", "grafana chart 10.5.14 -> 10.5.15 with persistence (same grafana version)",
       [helm("graf", "grafana-10.5.14", GFS)], [helm("graf", "grafana-10.5.15", GFS)], [P_GF], [S_GF]),
    S_(55, "test", "real-values", "grafana chart 10.5.15 installed without persistence: persistence.enabled true",
       [helm("graf", "grafana-10.5.15", GF)], [helm("graf", "grafana-10.5.15", GFS)], [P_GF], [S_GF]),
    S_(56, "test", "real-values", "grafana chart 10.5.15 with persistence: service.type NodePort",
       [helm("graf", "grafana-10.5.15", GFS)],
       [helm("graf", "grafana-10.5.15", merge(GFS, {"service": {"type": "NodePort"}}))], [P_GF], [S_GF]),
    S_(57, "test", "real-uninstall", "helm uninstall of grafana chart 10.5.15 with persistence",
       [helm("graf", "grafana-10.5.15", GFS)], [uninstall("graf")], [P_GF], [S_GF]),
    S_(58, "test", "real-values", "grafana chart 10.5.15 with persistence: adminPassword changed",
       [helm("graf", "grafana-10.5.15", GFS)],
       [helm("graf", "grafana-10.5.15", merge(GFS, {"adminPassword": "rotated-77e"}))], [P_GF], [S_GF]),
    S_(59, "test", "real-values", "grafana chart 10.5.15 defaults (no persistence): replicas 1 -> 2",
       [helm("graf", "grafana-10.5.15", GF)], [helm("graf", "grafana-10.5.15", merge(GF, {"replicas": 2}))],
       [P_GF], [S_GF]),
    # ---- bitnami
    S_(60, "test", "real-upgrade", "bitnami/postgresql 16.7.26 -> 16.7.27 (17.6.0-r0 -> r4)",
       [helm("bdb", "postgresql-16.7.26", BPG)], [helm("bdb", "postgresql-16.7.27", BPG)], [P_BPG], [S_BPG]),
    S_(61, "test", "real-values", "bitnami/postgresql 16.7.27: primary.persistence.enabled false",
       [helm("bdb", "postgresql-16.7.27", BPG)],
       [helm("bdb", "postgresql-16.7.27", merge(BPG, {"primary": {"persistence": {"enabled": False}}}))],
       [P_BPG], [S_BPG]),
    S_(62, "test", "real-values", "bitnami/postgresql 16.7.27, primary.networkPolicy.allowExternal false (client "
       "namespaces allowed by ingressNSMatchLabels): allowExternal set to true",
       [helm("bdb", "postgresql-16.7.27", merge(BPG, {"primary": {"networkPolicy": {
           "allowExternal": False, "ingressNSMatchLabels": {"role": "client"}}}}))],
       [helm("bdb", "postgresql-16.7.27", merge(BPG, {"primary": {"networkPolicy": {
           "allowExternal": True, "ingressNSMatchLabels": {"role": "client"}}}}))], [P_BPG], [S_BPG]),
    S_(63, "test", "real-values", "bitnami/postgresql 16.7.27: primary.service.type NodePort",
       [helm("bdb", "postgresql-16.7.27", BPG)],
       [helm("bdb", "postgresql-16.7.27", merge(BPG, {"primary": {"service": {"type": "NodePort"}}}))],
       [P_BPG], [S_BPG]),
    S_(64, "test", "real-upgrade", "bitnami/redis 21.2.6 -> 21.2.7 (8.0.2 -> 8.0.3)",
       [helm("brd", "redis-21.2.6", BRD)], [helm("brd", "redis-21.2.7", BRD)], [P_BRD], [S_BRD]),
    S_(65, "test", "real-values", "bitnami/redis 21.2.7: auth.enabled false",
       [helm("brd", "redis-21.2.7", BRD)], [helm("brd", "redis-21.2.7", merge(BRD, {"auth": {"enabled": False}}))],
       [P_BRD], [S_BRD]),
    S_(66, "test", "real-uninstall", "helm uninstall of bitnami/postgresql 16.7.27",
       [helm("bdb", "postgresql-16.7.27", BPG)], [uninstall("bdb")], [P_BPG], [S_BPG]),
    S_(67, "test", "real-values", "bitnami/postgresql 16.7.27: primary.extendedConfiguration added (max_connections)",
       [helm("bdb", "postgresql-16.7.27", BPG)],
       [helm("bdb", "postgresql-16.7.27", merge(BPG, {"primary": {"extendedConfiguration": "max_connections = 150"}}))],
       [P_BPG], [S_BPG]),
    # ---- kubernetes.io docs
    S_(68, "test", "real-docs", "docs deployment-update.yaml: nginx 1.14.2 -> 1.16.1 (2 replicas, no probe)",
       [apply(docs_nginx_deployment(2), svc("nginx", {"app": "nginx"}, 80))],
       [apply(docs_nginx_deployment(2, "nginx:1.16.1"))], [p_http("nginx")], adapted="probe Service added"),
    S_(69, "test", "real-docs", "docs nginx-deployment (3 replicas): image nginx:1.161 (the docs' typo example)",
       [apply(docs_nginx_deployment(3, "nginx:1.16.1"), svc("nginx", {"app": "nginx"}, 80))],
       [apply(docs_nginx_deployment(3, "nginx:1.161"))], [p_http("nginx")], adapted="probe Service added"),
    S_(70, "test", "real-docs", "docs deployment-scale.yaml: replicas 2 -> 4",
       [apply(docs_nginx_deployment(2), svc("nginx", {"app": "nginx"}, 80))], [apply(docs_nginx_deployment(4))],
       [p_http("nginx")], adapted="probe Service added"),
    S_(71, "test", "real-docs", "docs mysql single-instance: image mysql:9 -> mysql:8.4 (downgrade)",
       [apply(*docs_mysql_pv(), *docs_mysql("password"))], [apply(*docs_mysql("password", "mysql:8.4"))],
       [p_mysql("mysql", pw="password")], [s_mysql("app=mysql", pw="password")],
       adapted="hostPath and PV name per namespace, PV pre-bound"),
    S_(72, "test", "real-docs", "docs mysql single-instance cleanup: delete deployment, svc, pvc and pv",
       [apply(*docs_mysql_pv(), *docs_mysql("password"))],
       [delete(("deployment", "mysql"), ("service", "mysql"), ("persistentvolumeclaim", "mysql-pv-claim"),
               ("persistentvolume", "mysql-pv-volume-@NS@"))],
       [p_mysql("mysql", pw="password")], [s_mysql("app=mysql", pw="password")],
       adapted="hostPath and PV name per namespace, PV pre-bound"),
    S_(73, "test", "real-docs", "docs WordPress+MySQL mysql part: kubectl delete -k (secret, service, pvc, deployment)",
       [apply(*docs_wp_mysql())],
       [delete(("secret", "mysql-pass"), ("service", "wordpress-mysql"), ("persistentvolumeclaim", "mysql-pv-claim"),
               ("deployment", "wordpress-mysql"))],
       [p_mysql("wordpress-mysql")], [s_mysql("app=wordpress")], adapted="secretGenerator as a plain Secret"),
    S_(74, "test", "real-docs", "docs WordPress+MySQL mysql part: image mysql:8.0 -> mysql:8.4",
       [apply(*docs_wp_mysql())], [apply(*docs_wp_mysql("mysql:8.4"))],
       [p_mysql("wordpress-mysql")], [s_mysql("app=wordpress")], adapted="secretGenerator as a plain Secret"),
    S_(75, "test", "real-docs", "docs guestbook redis-leader: resources.limits added",
       [apply(*docs_redis_leader())],
       [apply(docs_redis_leader(resources={"requests": {"cpu": "100m", "memory": "100Mi"},
                                           "limits": {"cpu": "500m", "memory": "256Mi"}})[0])],
       [p_redis("redis-leader")], [s_redis("app=redis")], adapted="image docker.io/redis:6.0.5"),
    S_(76, "test", "real-docs", "docs StatefulSet tutorial web (2 replicas): image update",
       [apply(*DOCS_WEB_SVC, docs_web_sts())], [apply(docs_web_sts("nginx:1.27-alpine"))], [p_tcp("web", 80)],
       adapted="nginx alpine instead of nginx-slim; ClusterIP Service web for the probe"),
    S_(77, "test", "real-docs", "docs StatefulSet tutorial web: partition 3 with an image update",
       [apply(*DOCS_WEB_SVC, docs_web_sts())], [apply(docs_web_sts("nginx:1.27-alpine", partition=3))],
       [p_tcp("web", 80)], adapted="nginx alpine instead of nginx-slim; ClusterIP Service web for the probe"),
    S_(78, "test", "real-docs", "docs StatefulSet tutorial web: scale 2 -> 1",
       [apply(*DOCS_WEB_SVC, docs_web_sts())], [apply(docs_web_sts(replicas=1))], [p_tcp("web", 80)],
       adapted="nginx alpine instead of nginx-slim; ClusterIP Service web for the probe"),
    S_(79, "test", "real-docs", "docs allow-all-ingress NetworkPolicy added next to a client-namespace-only policy",
       [apply(web(), svc("web", {"app": "web"}, 80), np_from_ns("web-clients", {"app": "web"}, {"role": "client"}))],
       [apply(NP_ALLOW_ALL)], [p_http("web")], adapted="written workload"),
    S_(80, "test", "real-docs", "docs default-deny-ingress NetworkPolicy deleted (it was the only policy)",
       [apply(web(), svc("web", {"app": "web"}, 80), NP_DEFAULT_DENY,
              np_from_ns("web-clients", {"app": "web"}, {"role": "client"}))],
       [delete(("networkpolicy", "default-deny-ingress"), ("networkpolicy", "web-clients"))], [p_http("web")],
       adapted="written workload; both policies deleted (the namespace had nothing else)"),
    S_(81, "test", "real-docs", "docs default-deny-ingress NetworkPolicy applied to a namespace serving clients",
       [apply(web(), svc("web", {"app": "web"}, 80))], [apply(NP_DEFAULT_DENY)], [p_http("web")],
       adapted="written workload"),
    S_(82, "test", "real-docs", "docs RBAC read-secrets: ClusterRole secret-reader bound to user dave in the namespace",
       [apply(web(), svc("web", {"app": "web"}, 80), APP_SECRET)],
       [apply(SECRET_READER_CR, rolebinding("read-secrets", "ClusterRole", "secret-reader-@NS@", [U_DAVE]))],
       [p_http("web")], adapted="ClusterRole name per namespace"),
    S_(83, "test", "real-docs", "docs RBAC: rolebinding of ClusterRole edit to group system:serviceaccounts:<ns>",
       [apply(web(), svc("web", {"app": "web"}, 80), APP_SECRET)],
       [apply(rolebinding("serviceaccounts-edit", "ClusterRole", "edit", [G_SA_NS]))], [p_http("web")],
       adapted="docs use view for this command; edit is the next built-in role"),
    S_(84, "test", "real-docs", "docs RBAC: clusterrolebinding serviceaccounts-view (view to all service accounts)",
       [apply(web(), svc("web", {"app": "web"}, 80), APP_SECRET)],
       [apply(crb("serviceaccounts-view-@NS@", "view", [G_SA_ALL]))], [p_http("web")], locks=[GLOBAL],
       adapted="binding name per namespace"),
    S_(85, "test", "real-docs", "docs: kubectl expose deployment --type=NodePort (Service created for the app)",
       [apply(web(), svc("web", {"app": "web"}, 80))], [apply(svc("web-nodeport", {"app": "web"}, 80, typ="NodePort"))],
       [p_http("web")], adapted="written workload"),
    # ---- written
    S_(86, "test", "written", "web Deployment 3 replicas: Service targetPort 80 -> 8080 (nothing listens on 8080)",
       [apply(web(replicas=3), svc("web", {"app": "web"}, 80))], [apply(svc("web", {"app": "web"}, 80, target=8080))],
       [p_http("web")]),
    S_(87, "test", "written", "web Deployment 2 replicas: container port renamed http -> web; Service targetPort 'http'",
       [apply(web(port_name="http"), svc("web", {"app": "web"}, 80, target="http"))],
       [apply(web(port_name="web"))], [p_http("web")]),
    S_(88, "test", "written", "web Deployment 4 replicas: maxUnavailable 100% with an image bump",
       [apply(web(replicas=4), svc("web", {"app": "web"}, 80))],
       [apply(web(replicas=4, image="nginx:1.27-alpine",
                  strategy={"type": "RollingUpdate", "rollingUpdate": {"maxSurge": 0, "maxUnavailable": "100%"}}))],
       [p_http("web")]),
    S_(89, "test", "written", "postgres StatefulSet with PVC retention whenDeleted Delete: the StatefulSet is deleted",
       [apply(PG_SECRET, svc("pg", {"app": "pg"}, 5432), pg_sts({"whenDeleted": "Delete", "whenScaled": "Retain"}))],
       [delete(("statefulset", "pg"))], [P_PG], [S_PG]),
    S_(90, "test", "written", "postgres Deployment on a Retain PVC: Deployment and PVC deleted",
       [apply(PG_SECRET, svc("pg", {"app": "pg"}, 5432), pvc("pg-data", "retain"), pg_dep_pvc())],
       [delete(("deployment", "pg"), ("persistentvolumeclaim", "pg-data"))], [P_PG], [S_PG]),
    S_(91, "test", "written", "postgres NetworkPolicy namespaceSelector changed from client namespaces to {}",
       [apply(PG_SECRET, svc("pg", {"app": "pg"}, 5432), pg_sts(), np_from_ns("pg-clients", {"app": "pg"}, {"role": "client"}))],
       [apply(np_from_ns("pg-clients", {"app": "pg"}, None))], [P_PG], [S_PG]),
    S_(92, "test", "written", "postgres Deployment on a PVC: image postgres:17-alpine -> postgres:18-alpine",
       [apply(PG_SECRET, svc("pg", {"app": "pg"}, 5432), pvc("pg-data"), pg_dep_pvc())],
       [apply(pg_dep_pvc("postgres:18-alpine"))], [P_PG], [S_PG]),
    S_(93, "test", "written", "web Deployment 2 replicas: strategy changed to Recreate (no template change)",
       [apply(web(), svc("web", {"app": "web"}, 80))], [apply(web(strategy={"type": "Recreate"}))], [p_http("web")]),
    S_(94, "test", "written", "postgres StatefulSet: the PVC is deleted while the pod still mounts it",
       [apply(PG_SECRET, svc("pg", {"app": "pg"}, 5432), pg_sts())], [delete(("persistentvolumeclaim", "data-pg-0"))],
       [P_PG], [S_PG]),
    S_(95, "test", "written", "Role granting get/list secrets bound to the vk-outside default ServiceAccount",
       [apply(web(), svc("web", {"app": "web"}, 80), APP_SECRET)],
       [apply({"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role", "metadata": {"name": "secret-read"},
               "rules": [{"apiGroups": [""], "resources": ["secrets"], "verbs": ["get", "list"]}]},
              rolebinding("secret-read", "Role", "secret-read",
                          [{"kind": "ServiceAccount", "name": "default", "namespace": "vk-outside"}]))],
       [p_http("web")]),
]
BY_ID = {s["id"]: s for s in S}
