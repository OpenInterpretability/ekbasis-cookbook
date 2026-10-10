"""WS-K8S: small helpers around kubectl for the private kind cluster `ekb-k8s` (never any other context)."""
from __future__ import annotations

import json
import os
import subprocess
import time

JOB = os.environ.get("CLAUDE_JOB_DIR", "<job>")
K8S_TMP = os.path.join(JOB, "tmp", "k8s")
KUBECONFIG = os.environ.get("K8S_KUBECONFIG", os.path.join(K8S_TMP, "kubeconfig"))
KUBECTL = os.path.join(K8S_TMP, "bin", "kubectl")
CONTEXT = "kind-ekb-k8s"
NODES = ["ekb-k8s-control-plane", "ekb-k8s-worker", "ekb-k8s-worker2"]


HARNESS_HOME = os.path.join(K8S_TMP, "harness_home")  # kubectl writes its discovery cache under $HOME/.kube: never the real HOME


def env():
    e = dict(os.environ)
    e["KUBECONFIG"] = KUBECONFIG
    e["HOME"] = HARNESS_HOME
    os.makedirs(HARNESS_HOME, exist_ok=True)
    e["PATH"] = os.path.dirname(KUBECTL) + os.pathsep + e.get("PATH", "")
    return e


def check_context():
    out = subprocess.run([KUBECTL, "config", "get-contexts", "-o", "name"], capture_output=True, text=True, env=env())
    names = out.stdout.split()
    if names != [CONTEXT]:
        raise RuntimeError(f"kubeconfig must hold only {CONTEXT}, found {names}")


def kc(*args, stdin: str | None = None, timeout: float = 90, check: bool = True, cwd: str | None = None):
    """Run kubectl with the private kubeconfig and the explicit context. Returns CompletedProcess."""
    cmd = [KUBECTL, "--context", CONTEXT, *args]
    p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout, env=env(), cwd=cwd)
    if check and p.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)[:200]} -> {p.returncode}: {p.stderr.strip()[:400]}")
    return p


def kj(*args, timeout: float = 60) -> dict:
    return json.loads(kc(*args, "-o", "json", timeout=timeout).stdout)


def items(kind: str, ns: str | None = None) -> list:
    args = ["get", kind] + (["-n", ns] if ns else [])
    p = kc(*args, "-o", "json", check=False)
    if p.returncode != 0:
        return []
    return json.loads(p.stdout).get("items", [])


def run_shell(command: str, cwd: str, timeout: float = 150):
    """Run a scenario's kubectl command line exactly as written (a shell line), with the private kubeconfig and the
    v1.37 client first on PATH. Returns (exit code, stdout, stderr, seconds); a timeout is exit code 124."""
    t0 = time.time()
    try:
        p = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=timeout, env=env(), cwd=cwd,
                           stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr, round(time.time() - t0, 2)
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), \
            "timeout", round(time.time() - t0, 2)


def node_exec(node: str, sh: str, timeout: float = 30):
    if node not in NODES:
        raise ValueError(f"not a node of ekb-k8s: {node}")
    p = subprocess.run(["docker", "exec", node, "sh", "-c", sh], capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout.strip()


def pv_location(pv: dict):
    """(node, path) of a local-path volume."""
    spec = pv.get("spec", {})
    path = (spec.get("hostPath") or {}).get("path") or (spec.get("local") or {}).get("path")
    node = None
    for term in ((spec.get("nodeAffinity") or {}).get("required") or {}).get("nodeSelectorTerms", []):
        for ex in term.get("matchExpressions", []):
            if ex.get("key") == "kubernetes.io/hostname" and ex.get("values"):
                node = ex["values"][0]
    return node, path


def payload_bytes(node: str | None, path: str | None):
    """Size of payload.txt in a volume folder on its node, or None if it is not there."""
    if not node or not path:
        return None
    rc, out = node_exec(node, f'if [ -f "{path}/payload.txt" ]; then wc -c < "{path}/payload.txt"; else echo NONE; fi')
    if rc != 0 or out.strip() == "NONE":
        return None
    try:
        return int(out.split()[0])
    except (ValueError, IndexError):
        return None
