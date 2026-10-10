"""WS-K8S Phase 0 truth runner (SPEC_probe.md §3): every scenario for real on the kind cluster, observed, judged.

    python3 truth.py --pass A [--only ID ...] [--parallel 3]
Writes data/truth_<pass>.jsonl (one row per scenario: rendered command and files, the forecasters' summary, raw
snapshots, the command's output, the restart test, the final volume check, the truth). Resumable: ids already in the
file are skipped. F6 (exclusive: taints touch nodes) runs alone, before the others.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import shlex
import shutil
import sys
import tempfile
import threading
import time
import traceback

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kube  # noqa: E402
import observe  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
LOCK = threading.Lock()
KIND = {"namespace": "namespaces", "namespaces": "namespaces", "ns": "namespaces", "deployment": "deployments",
        "deployments": "deployments", "deploy": "deployments", "daemonset": "daemonsets", "daemonsets": "daemonsets",
        "ds": "daemonsets", "statefulset": "statefulsets", "statefulsets": "statefulsets", "sts": "statefulsets",
        "configmap": "configmaps", "configmaps": "configmaps", "cm": "configmaps", "service": "services",
        "services": "services", "svc": "services", "persistentvolumeclaim": "persistentvolumeclaims",
        "pvc": "persistentvolumeclaims", "job": "jobs", "jobs": "jobs", "replicaset": "replicasets", "rs": "replicasets"}
OBJ_KIND = {"Namespace": "namespaces", "Deployment": "deployments", "StatefulSet": "statefulsets",
            "DaemonSet": "daemonsets", "Service": "services", "ConfigMap": "configmaps", "Job": "jobs",
            "PersistentVolumeClaim": "persistentvolumeclaims", "ResourceQuota": "resourcequotas"}


def log(*a):
    with LOCK:
        print(time.strftime("%H:%M:%S"), *a, flush=True)


def render(spec, sfx):
    return json.loads(json.dumps(spec).replace("@SFX@", sfx))


def targets(command, files, default_ns):
    """(kind, ns, name) the command itself targets: named on the line or defined in the files it reads."""
    t = shlex.split(command)
    args = t[1:]
    ns = default_ns
    pos, fpaths, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a in ("-n", "--namespace"):
            ns = args[i + 1]
            i += 2
            continue
        if a in ("-f", "--filename"):
            fpaths.append(args[i + 1])
            i += 2
            continue
        if a in ("-p", "--patch", "-l", "--selector", "--type", "--replicas", "--cascade"):
            i += 2
            continue
        if not a.startswith("-"):
            pos.append(a)
        i += 1
    out = set()
    verb = pos[0] if pos else ""
    if verb in ("delete", "scale", "patch"):
        rest = pos[1:]
        if rest and "/" in rest[0]:
            k, n = rest[0].split("/", 1)
            out.add((KIND.get(k, k), None if KIND.get(k) == "namespaces" else ns, n))
        elif len(rest) >= 2:
            k = KIND.get(rest[0], rest[0])
            for n in rest[1:]:
                out.add((k, None if k == "namespaces" else ns, n))
    for fp in fpaths:
        for path, txt in files.items():
            if path == fp or path.startswith(fp.rstrip("/") + "/"):
                for doc in yaml.safe_load_all(txt):
                    if doc:
                        k = OBJ_KIND.get(doc["kind"], doc["kind"].lower() + "s")
                        out.add((k, None if k == "namespaces" else doc["metadata"].get("namespace", ns),
                                 doc["metadata"]["name"]))
    return out


def create_objects(spec):
    for step in spec["pre_steps"]:
        kube.kc(*step)
    for o in spec["objects"]:
        y = yaml.safe_dump(o["obj"], sort_keys=False)
        if o["method"] == "apply":
            kube.kc("apply", "-f", "-", stdin=y)
        else:
            kube.kc("create", "-f", "-", stdin=y)


def _match(labels, sel):
    return bool(sel) and all(labels.get(k) == v for k, v in sel.items())


def wait_ready(spec, timeout=120):
    """Workloads ready, claims bound, data written, endpoints caught up."""
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout:
        ok, why = True, []
        for ns in spec["namespaces"]:
            for d in kube.items("deployments.apps", ns) + kube.items("statefulsets.apps", ns):
                if (d.get("status", {}).get("readyReplicas") or 0) != d["spec"].get("replicas"):
                    ok = False
                    why.append(f"{d['metadata']['name']} not ready")
            for d in kube.items("daemonsets.apps", ns):
                st = d.get("status", {})
                if not st.get("desiredNumberScheduled") or st.get("numberReady") != st.get("desiredNumberScheduled"):
                    ok = False
                    why.append(f"ds {d['metadata']['name']} not ready")
            for c in kube.items("persistentvolumeclaims", ns):
                if c.get("status", {}).get("phase") != "Bound":
                    ok = False
                    why.append(f"pvc {c['metadata']['name']} not bound")
            pods = kube.items("pods", ns)
            slices = kube.items("endpointslices.discovery.k8s.io", ns)
            for s in kube.items("services", ns):
                want = sum(1 for p in pods if observe._pod_ready(p) and not p["metadata"].get("deletionTimestamp")
                           and _match(p["metadata"].get("labels") or {}, s["spec"].get("selector")))
                if observe._ready_endpoints(slices, s["metadata"]["name"]) != want:
                    ok = False
                    why.append(f"svc {s['metadata']['name']} endpoints behind")
        if ok:
            for pv in kube.items("persistentvolumes"):
                ref = pv["spec"].get("claimRef") or {}
                if ref.get("namespace") in spec["namespaces"]:
                    node, path = kube.pv_location(pv)
                    if kube.payload_bytes(node, path) is None:
                        ok = False
                        why.append(f"pv {pv['metadata']['name']} no data yet")
        if ok:
            return True, round(time.time() - t0, 1)
        last = "; ".join(why[:4])
        time.sleep(2)
    return False, last


def settle(namespaces, first_wait=20, max_wait=120):
    time.sleep(first_wait)
    t0 = time.time()
    prev, same = None, 0
    while time.time() - t0 < max_wait:
        sig = observe.signature(namespaces)
        same = same + 1 if sig == prev else 0
        prev = sig
        if same >= 4:
            return round(first_wait + time.time() - t0, 1), True
        time.sleep(3)
    return round(first_wait + time.time() - t0, 1), False


def workload_pods(ns, kind, name):
    pods = kube.items("pods", ns)
    if kind == "statefulsets":
        own = {f"StatefulSet/{name}"}
    else:
        own = {f"ReplicaSet/{r['metadata']['name']}" for r in kube.items("replicasets.apps", ns)
               if observe._owner(r) == f"Deployment/{name}"}
    return sorted((p for p in pods if observe._owner(p) in own), key=lambda p: p["metadata"]["name"])


def restart_test(after):
    """SPEC §3: one workload at a time, delete its first pod; ok if within 60 s the deleted pod is gone and the workload
    has >= max(1, ready before) ready pods."""
    res = []
    for w in sorted(after["workloads"], key=lambda w: (w["kind"], w["ns"], w["name"])):
        if not w["replicas"]:
            continue
        kind_obj = "deployment" if w["kind"] == "deployments" else "statefulset"
        cur = kube.kc("get", kind_obj, w["name"], "-n", w["ns"], "-o", "json", check=False)
        if cur.returncode != 0:
            res.append({"workload": f"{w['kind']}/{w['ns']}/{w['name']}", "ok": None, "note": "gone"})
            continue
        r0 = json.loads(cur.stdout).get("status", {}).get("readyReplicas") or 0
        pods = workload_pods(w["ns"], w["kind"], w["name"])
        victim = pods[0] if pods else None
        if victim:
            kube.kc("delete", "pod", victim["metadata"]["name"], "-n", w["ns"], "--wait=false", check=False)
        need = max(1, r0)
        t0, ok = time.time(), False
        while time.time() - t0 < 60:
            time.sleep(2)
            gone = True
            if victim:
                p = kube.kc("get", "pod", victim["metadata"]["name"], "-n", w["ns"], "-o", "jsonpath={.metadata.uid}",
                            check=False)
                gone = p.returncode != 0 or p.stdout.strip() != victim["metadata"]["uid"]
            st = kube.kc("get", kind_obj, w["name"], "-n", w["ns"], "-o", "jsonpath={.status.readyReplicas}", check=False)
            ready = int(st.stdout.strip() or 0) if st.returncode == 0 else 0
            if gone and ready >= need:
                ok = True
                break
        res.append({"workload": f"{w['kind']}/{w['ns']}/{w['name']}", "ok": ok, "ready_before": r0, "need": need,
                    "victim": victim["metadata"]["name"] if victim else None, "secs": round(time.time() - t0, 1)})
    return res


def compute_truth(before, after, final_pvs, restart, exit_code, tg):
    run_before = {p["uid"] for p in before["pods"] if p["phase"] == "Running" and not p["deleting"]}
    run_after = {p["uid"] for p in after["pods"] if p["phase"] == "Running" and not p["deleting"]}
    svc_after = {(s["ns"], s["name"]): s["ready"] for s in after["services"]}
    after_uids = {o["uid"] for o in after["objects"]} | {v["uid"] for v in after["namespaces"].values()}
    final_pv_uids = {v["uid"] for v in final_pvs["pvs"]}
    deleted = []
    for o in before["objects"]:
        if o["uid"] not in after_uids and (o["kind"], o["ns"], o["name"]) not in tg:
            deleted.append(f"{o['kind']}/{o['ns']}/{o['name']}")
    for ns, v in before["namespaces"].items():
        if v["uid"] not in after_uids and ("namespaces", None, ns) not in tg:
            deleted.append(f"namespaces/{ns}")
    for pv in before["pvs"]:
        if pv["uid"] not in final_pv_uids:
            deleted.append(f"persistentvolumes/{pv['name']}")
    lost = [pv["name"] for pv in before["pvs"] if pv["payload"] is not None and final_pvs["payload"].get(pv["name"]) is None]
    t = {
        "fails": exit_code != 0,
        "pods_terminated": bool(run_before - run_after),
        "outage": any(s["ready"] >= 1 and svc_after.get((s["ns"], s["name"]), 0) == 0 for s in before["services"]),
        "data_lost": bool(lost),
        "replicas_short": any((w["replicas"] or 0) > (w["ready"] or 0) for w in after["workloads"]),
        "deletes_unnamed": bool(deleted),
        "restart_breaks": any(r["ok"] is False for r in restart),
    }
    detail = {"terminated_pods": sorted(p["name"] for p in before["pods"] if p["uid"] in run_before - run_after),
              "outage_services": sorted(f"{s['ns']}/{s['name']}" for s in before["services"]
                                        if s["ready"] >= 1 and svc_after.get((s["ns"], s["name"]), 0) == 0),
              "lost_volumes": lost, "deleted_objects": sorted(deleted),
              "short_workloads": sorted(f"{w['kind']}/{w['name']} {w['ready']}/{w['replicas']}" for w in after["workloads"]
                                        if (w["replicas"] or 0) > (w["ready"] or 0)),
              "restart_failures": [r["workload"] for r in restart if r["ok"] is False]}
    return t, detail


def teardown(spec, before_pvs):
    for step in spec.get("teardown_steps", []):
        kube.kc(*step, check=False)
    for ns in spec["namespaces"]:
        kube.kc("delete", "namespace", ns, "--ignore-not-found", "--wait=true", "--timeout=180s", check=False, timeout=200)
    names = {p["name"] for p in before_pvs}
    for pv in kube.items("persistentvolumes"):
        ref = pv["spec"].get("claimRef") or {}
        if ref.get("namespace") in spec["namespaces"] or pv["metadata"]["name"] in names:
            node, path = kube.pv_location(pv)
            kube.kc("delete", "pv", pv["metadata"]["name"], "--wait=false", check=False)
            if node and path and path.startswith("/var/local-path-provisioner/"):
                kube.node_exec(node, f'rm -rf "{path}"')
    for p in before_pvs:  # retained folders whose PV object is already gone
        if p.get("node") and p.get("path", "").startswith("/var/local-path-provisioner/"):
            kube.node_exec(p["node"], f'rm -rf "{p["path"]}"')


def run_one(spec0, pass_id, attempt=0):
    sfx = hashlib.sha256(f"{pass_id}|{spec0['id']}|{attempt}".encode()).hexdigest()[:4]
    spec = render(spec0, sfx)
    row = {"id": spec["id"], "family": spec["family"], "instance": spec["instance"], "twin": spec["twin"],
           "pair": spec["pair"], "pass": pass_id, "sfx": sfx, "attempt": attempt, "command": spec["command"],
           "files": spec["files"], "key_question": spec0.get("key_question"), "rules": spec0.get("rules")}
    work = tempfile.mkdtemp(prefix=f"k8s_{spec['id']}_", dir=os.path.join(kube.K8S_TMP, "work"))
    before = {"pvs": []}
    try:
        for path, txt in spec["files"].items():
            fp = os.path.join(work, path)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            open(fp, "w").write(txt)
        create_objects(spec)
        ok, info = wait_ready(spec)
        for step in spec["post_steps"]:
            kube.kc(*step)
        if not ok:
            raise RuntimeError(f"setup not ready: {info}")
        if spec["post_steps"]:
            time.sleep(2)
        row["setup_secs"] = info
        row["summary"] = observe.summarize(spec["namespaces"], spec["files"])
        before = observe.snapshot(spec["namespaces"])
        row["before"] = before
        rc, out, err, secs = kube.run_shell(spec["command"], cwd=work)
        row.update({"exit_code": rc, "stdout": out[-4000:], "stderr": err[-4000:], "cmd_secs": secs})
        row["settle_secs"], row["settled"] = settle(spec["namespaces"])
        after = observe.snapshot(spec["namespaces"], pv_names=[p["name"] for p in before["pvs"]])
        row["after"] = after
        row["restart"] = restart_test(after)
        final = observe.snapshot(spec["namespaces"], pv_names=[p["name"] for p in before["pvs"]])
        final_payload = {pv["name"]: kube.payload_bytes(pv["node"], pv["path"]) for pv in before["pvs"]}
        row["final_pvs"] = {"pvs": final["pvs"], "payload": final_payload}
        tg = targets(spec["command"], spec["files"], spec["namespaces"][0])
        row["targets"] = sorted(map(list, ((k, n or "", m) for k, n, m in tg)))
        row["truth"], row["truth_detail"] = compute_truth(before, after, row["final_pvs"], row["restart"], rc, tg)
    except Exception as e:  # noqa: BLE001
        row["error"] = f"{type(e).__name__}: {e}"
        row["trace"] = traceback.format_exc()[-1500:]
    finally:
        try:
            teardown(spec, before.get("pvs", []))
        except Exception as e:  # noqa: BLE001
            row["teardown_error"] = repr(e)
        shutil.rmtree(work, ignore_errors=True)
    if "error" in row and attempt == 0 and str(row["error"]).startswith("RuntimeError: setup not ready"):
        log(spec["id"], pass_id, "setup failed, retrying once:", row["error"][:120])
        return run_one(spec0, pass_id, attempt=1)
    return row


def nodes_clean():
    for n in kube.items("nodes"):
        bad = [t for t in n["spec"].get("taints") or [] if not t["key"].startswith("node-role.kubernetes.io/")]
        if bad or n["spec"].get("unschedulable"):
            raise RuntimeError(f"node {n['metadata']['name']} not clean: taints {bad}, unschedulable {n['spec'].get('unschedulable')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass", dest="pass_id", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--scenarios", default=os.path.join(DATA, "scenarios.jsonl"))
    a = ap.parse_args()
    kube.check_context()
    os.makedirs(os.path.join(kube.K8S_TMP, "work"), exist_ok=True)
    scen = [json.loads(l) for l in open(a.scenarios)]
    if a.only:
        scen = [s for s in scen if s["id"] in a.only or s["family"] in a.only]
    out_path = os.path.join(DATA, f"truth_{a.pass_id}.jsonl")
    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["id"] for l in open(out_path)}
    todo = [s for s in scen if s["id"] not in done]
    log(f"pass {a.pass_id}: {len(todo)} to run ({len(done)} done)")

    def record(row):
        with LOCK:
            with open(out_path, "a") as f:
                f.write(json.dumps(row) + "\n")
        t = row.get("truth")
        log(row["id"], "ERROR " + row["error"][:150] if "error" in row else
            " ".join(k for k, v in (t or {}).items() if v) or "(nothing)", f"[exit {row.get('exit_code')}]")

    for s in [s for s in todo if s["exclusive"]]:
        nodes_clean()
        record(run_one(s, a.pass_id))
    nodes_clean()
    rest = [s for s in todo if not s["exclusive"]]
    with cf.ThreadPoolExecutor(a.parallel) as ex:
        for row in ex.map(lambda s: run_one(s, a.pass_id), rest):
            record(row)
    nodes_clean()
    log("pass done")


if __name__ == "__main__":
    main()
