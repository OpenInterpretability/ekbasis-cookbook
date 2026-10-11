"""Small helpers shared by runner.py and facts.py: kubectl/helm calls, rendering scenario objects into a namespace."""
from __future__ import annotations

import json
import os
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
KCFG = os.path.join(ROOT, "kubeconfig")
HELM = os.path.join(ROOT, "bin", "helm")
NODE = "vk8s-control-plane"
OUTSIDER = "vk8s-outsider"      # a plain container on the kind docker network: "outside the cluster"
ENV = dict(os.environ, KUBECONFIG=KCFG, HELM_CACHE_HOME=os.path.join(ROOT, ".helm", "cache"),
           HELM_CONFIG_HOME=os.path.join(ROOT, ".helm", "config"), HELM_DATA_HOME=os.path.join(ROOT, ".helm", "data"))
CLUSTER_SCOPED = {"ClusterRole", "ClusterRoleBinding", "Namespace", "StorageClass", "PersistentVolume"}


def sh(args, timeout=120, stdin=None):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=ENV, input=stdin)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        return 124, "", f"timeout after {timeout}s: {e}"


def k(*args, timeout=120, stdin=None):
    return sh(["kubectl", *args], timeout=timeout, stdin=stdin)


def kj(*args, timeout=60):
    rc, out, err = k(*args, "-o", "json", timeout=timeout)
    if rc:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def helm(*args, timeout=600):
    return sh([HELM, *args], timeout=timeout)


def render(obj, ns):
    o = json.loads(json.dumps(obj).replace("@NS@", ns))
    if o["kind"] not in CLUSTER_SCOPED:
        o["metadata"]["namespace"] = ns
    else:
        o.setdefault("metadata", {}).setdefault("labels", {})["vk8s-scenario"] = ns
    return o


def as_list(objs):
    return json.dumps({"apiVersion": "v1", "kind": "List", "items": objs})


def node_ip():
    rc, out, _ = sh(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", NODE])
    return out.strip()


def node_sh(cmd, timeout=60):
    return sh(["docker", "exec", NODE, "sh", "-c", cmd], timeout=timeout)


def pexec(cmd, ns="vk-probe", timeout=30):
    """Run a shell command in a prober pod (vk-probe = the clients; vk-outside = a pod of another namespace)."""
    return k("exec", "-n", ns, "prober", "--", "sh", "-c", cmd, timeout=timeout)


def chart_path(name):
    return os.path.join(ROOT, "charts", name)
