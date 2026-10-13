"""WS-K8S chain study v2: LONG pipelines (7-10 steps that change the cluster). The same 18 tasks as chain_tasks.py
(scenarios, judges, simulated user, harmful step and its order kept), with harmless pipeline bookkeeping steps added
around the original steps: annotations, labels, a ConfigMap and a Secret of the pipeline's own (on the node for the
node tasks). Steps after a namespace deletion would act on a deleted namespace, so there every added step comes first.
pipeline.sh as in chain_tasks.py (--steps A-B)."""
from __future__ import annotations

import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chain_tasks as CT  # noqa: E402

W2 = "ekb-k8s-worker2"


def ns_steps(ns):
    return [f"kubectl annotate namespace {ns} pipeline-run=r1 --overwrite",
            f"kubectl create configmap pipeline-meta -n {ns} --from-literal=run=r1",
            f"kubectl label configmap pipeline-meta -n {ns} stage=pre --overwrite",
            f"kubectl create secret generic pipeline-token -n {ns} --from-literal=token=x1",
            f"kubectl annotate configmap pipeline-meta -n {ns} checked=yes --overwrite",
            f"kubectl label namespace {ns} pipeline=v2 --overwrite",
            f"kubectl annotate secret pipeline-token -n {ns} rotated=no --overwrite"]


def node_steps():
    return [f"kubectl label nodes {W2} pool=batch --overwrite",
            f"kubectl annotate nodes {W2} maintenance-window=sunday --overwrite",
            f"kubectl label nodes {W2} zone-hint=b --overwrite",
            f"kubectl annotate nodes {W2} owner=platform --overwrite",
            f"kubectl label nodes {W2} tier-hint=general --overwrite",
            f"kubectl annotate nodes {W2} checked=yes --overwrite",
            f"kubectl annotate nodes {W2} pipeline-run=r1 --overwrite"]


def lengthen(tid, steps):
    key = tid.split("_")[0]
    base = CT.NS[key]
    extra = node_steps() if base is None else ns_steps(f"{base}-@SFX@")
    if any("delete namespace" in s for s in steps):
        return extra[:6] + steps          # nothing can follow the namespace's deletion
    return extra[:4] + steps + extra[4:7]


TASKS = []
for t in CT.TASKS:
    tid = t["id"][2:]
    sp = CT.SPEC[tid]
    steps = lengthen(tid, sp["steps"])
    u = dict(t)
    u["id"] = "L_" + tid
    u["make"] = CT._make(CT.BASE[tid]["make"], sp["title"], steps)
    u["pipeline"] = steps
    u["intent"] = copy.deepcopy(t["intent"])
    TASKS.append(u)

respond = CT.respond
steps_of = CT.steps_of
