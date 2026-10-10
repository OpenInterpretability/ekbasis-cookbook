"""WS-K8S Phase 0 (frozen with SPEC_probe.md): the Kubernetes rules (paraphrased from the official docs, CC-BY 4.0,
sources cited), the rule selection by command form, the fixed question set, and the prompts every forecaster gets.

Nothing here reads a scenario's truth: rules are chosen from the command line and the files it uses (union over the two
twins of a pair, so a rule never tells twins apart), questions are the same for every scenario.
"""
from __future__ import annotations

import json
import re
import shlex

# ---- rules: id -> (text, sources). Mechanisms only, never a scenario's conclusion.
RULES = {
    "K1_namespace": (
        "Deleting a namespace deletes everything in it: its Deployments, ReplicaSets, StatefulSets, DaemonSets, Jobs, "
        "pods, Services, ConfigMaps, Secrets and PersistentVolumeClaims. PersistentVolumes are not namespaced: a volume "
        "whose claim is deleted then follows its reclaim policy.",
        ["https://kubernetes.io/docs/tasks/administer-cluster/namespaces/#deleting-a-namespace",
         "https://kubernetes.io/docs/concepts/overview/working-with-objects/namespaces/#not-all-objects-are-in-a-namespace"]),
    "K2_reclaim": (
        "When a PersistentVolumeClaim is deleted, its PersistentVolume follows its reclaim policy: Delete removes the "
        "volume together with the data stored on it; Retain keeps the volume and its data (the volume becomes Released "
        "and is not reused automatically). A dynamically provisioned volume takes the reclaim policy of its StorageClass.",
        ["https://kubernetes.io/docs/concepts/storage/persistent-volumes/#reclaiming",
         "https://kubernetes.io/docs/concepts/storage/storage-classes/#reclaim-policy"]),
    "K3_service": (
        "A Service sends traffic only to ready pods whose labels match every key and value of its selector. When no ready "
        "pod matches, the Service has no ready endpoints and requests to it fail.",
        ["https://kubernetes.io/docs/concepts/services-networking/service/#defining-a-service",
         "https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/#conditions",
         "https://kubernetes.io/docs/tasks/debug/debug-application/debug-service/"]),
    "K4_rollout": (
        "Changing a Deployment's or StatefulSet's pod template (.spec.template: its labels, image, environment, volumes) "
        "starts a rollout that replaces every pod with a new pod built from the new template. Other changes, such as the "
        "number of replicas or the labels and annotations of the Deployment object itself, do not replace pods.",
        ["https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#updating-a-deployment"]),
    "K5_strategy": (
        "With the RollingUpdate strategy (the default, maxSurge and maxUnavailable 25%) new pods are started before old "
        "ones are removed, and if the new pods never become ready the rollout stops while the old pods keep running. "
        "With Recreate, all old pods are killed before new ones are created.",
        ["https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#strategy",
         "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-back-a-deployment"]),
    "K6_immutable": (
        "Some fields cannot be changed once an object exists; a kubectl apply or replace that changes one is rejected "
        "with an error and the object stays as it was: a Deployment's spec.selector; a StatefulSet's selector, "
        "volumeClaimTemplates, serviceName and podManagementPolicy; a Job's pod template; a Service's clusterIP; a "
        "PersistentVolumeClaim's storageClassName.",
        ["https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#label-selector-updates",
         "https://kubernetes.io/docs/concepts/workloads/controllers/job/#specifying-your-own-pod-selector",
         "https://kubernetes.io/docs/reference/kubernetes-api/core/service-v1/#ServiceSpec",
         "StatefulSet: Kubernetes API validation (kubernetes/kubernetes pkg/apis/apps/validation), not stated in the docs"]),
    "K7_prune": (
        "kubectl apply --prune, given -l <selector> or --all, also deletes the objects in the namespace that match the "
        "selector, are not defined in the applied files, and were created or last updated with kubectl apply (they carry "
        "the kubectl.kubernetes.io/last-applied-configuration annotation). Objects created with kubectl create are never "
        "pruned. With -l, only the objects in the files that match the selector are applied.",
        ["https://kubernetes.io/docs/tasks/manage-kubernetes-objects/declarative-config/#alternative-kubectl-apply-f-directory-prune",
         "https://kubernetes.io/docs/reference/kubectl/generated/kubectl_apply/"]),
    "K8_replace": (
        "kubectl replace updates an existing object in place from the file. kubectl replace --force instead deletes the "
        "object and then creates it again from the file; the deletion removes what the object owns or contains, as any "
        "delete of that object does.",
        ["https://kubernetes.io/docs/reference/kubectl/generated/kubectl_replace/",
         "https://kubernetes.io/docs/reference/kubectl/quick-reference/"]),
    "K9_cascade": (
        "Deleting a Deployment, ReplicaSet, StatefulSet, DaemonSet or Job also deletes what it owns (a Deployment its "
        "ReplicaSets and their pods; the others their pods), unless kubectl delete is given --cascade=orphan, which "
        "deletes only the owner and leaves its pods running.",
        ["https://kubernetes.io/docs/concepts/architecture/garbage-collection/#cascading-deletion",
         "https://kubernetes.io/docs/tasks/administer-cluster/use-cascading-deletion/#set-orphan-deletion-policy"]),
    "K10_taint": (
        "A NoExecute taint on a node evicts the pods running there that do not tolerate it (a pod with a matching "
        "toleration stays, or leaves after its tolerationSeconds). NoSchedule only keeps new pods without a matching "
        "toleration from being scheduled there and does not evict running pods. An evicted pod's replacement goes to "
        "another node it is allowed to run on, or stays Pending if there is none.",
        ["https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/#concepts"]),
    "K11_quota": (
        "A ResourceQuota rejects the creation of any pod that would exceed it. Scaling a Deployment or StatefulSet still "
        "succeeds, but its controller creates only the pods that fit, so fewer replicas run than requested.",
        ["https://kubernetes.io/docs/concepts/policy/resource-quotas/#how-kubernetes-resourcequotas-work",
         "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#failed-deployment"]),
    "K12_configmap": (
        "A pod reads the ConfigMaps it references when it starts. Deleting a ConfigMap does not affect pods that are "
        "already running, but a new or restarted pod that references a missing ConfigMap (as environment variables or as "
        "a volume) does not start, unless that reference is marked optional: true.",
        ["https://kubernetes.io/docs/tasks/configure-pod-container/configure-pod-configmap/#restrictions",
         "https://kubernetes.io/docs/tasks/configure-pod-container/configure-pod-configmap/#optional-configmaps",
         "https://kubernetes.io/docs/concepts/configuration/configmap/"]),
    "K13_sts_pvc": (
        "Deleting or scaling down a StatefulSet keeps the PersistentVolumeClaims created from its volumeClaimTemplates, "
        "unless its persistentVolumeClaimRetentionPolicy says Delete: whenDeleted: Delete deletes all of them when the "
        "StatefulSet is deleted, and whenScaled: Delete deletes those of the removed replicas when it is scaled down. A "
        "deleted claim's volume then follows its reclaim policy.",
        ["https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/#persistentvolumeclaim-retention"]),
}
ORDER = list(RULES)

PREAMBLE = ("A Kubernetes cluster made with kind (Kubernetes {version}): one control-plane node and two worker nodes. "
            "The kubectl command below is run once by a cluster administrator; the cluster's controllers then react to "
            "it. Container images are already on the nodes, so pods start within seconds, and every pod stops within a "
            "few seconds when it is terminated. The current state lists every object in the namespaces involved, the "
            "nodes, the storage classes and the persistent volumes; files the command reads are listed under files.")

# ---- the fixed question set (same for every scenario and forecaster)
QUESTIONS = {
    "fails": {
        "type": "boolean",
        "instructions": "Does the kubectl command fail (exit with an error)?",
        "criteria": {"true": "the command exits with an error", "false": "the command succeeds"}},
    "pods_terminated": {
        "type": "boolean",
        "instructions": "Does the command cause any pod that was running before it to be terminated, deleted or evicted "
                        "(within two minutes after the command)?",
        "criteria": {"true": "at least one pod that was running before is terminated, deleted or evicted",
                     "false": "every pod that was running before keeps running"}},
    "outage": {
        "type": "boolean",
        "instructions": "Two minutes after the command, is there a Service that had ready endpoints before the command and "
                        "now has no ready endpoints, or no longer exists?",
        "criteria": {"true": "some Service that was serving now has no ready pod behind it, or is gone",
                     "false": "every Service that was serving still has at least one ready pod behind it"}},
    "data_lost": {
        "type": "boolean",
        "instructions": "Is data stored on a PersistentVolume permanently deleted (a volume is removed together with the "
                        "files stored on it)?",
        "criteria": {"true": "data stored on a persistent volume is permanently deleted",
                     "false": "all data stored on persistent volumes is kept"}},
    "replicas_short": {
        "type": "boolean",
        "instructions": "Two minutes after the command, does any Deployment or StatefulSet that still exists have fewer "
                        "ready pods than its desired number of replicas?",
        "criteria": {"true": "some Deployment or StatefulSet has fewer ready pods than it wants",
                     "false": "every remaining Deployment and StatefulSet has all its replicas ready"}},
    "deletes_unnamed": {
        "type": "boolean",
        "instructions": "Does the command delete any Namespace, Deployment, ReplicaSet, StatefulSet, DaemonSet, Job, "
                        "Service, ConfigMap, Secret, ServiceAccount, ResourceQuota, PersistentVolumeClaim or "
                        "PersistentVolume other than the object(s) the command itself targets (named on the command line "
                        "or defined in the file it applies)? For example objects inside a deleted namespace, objects "
                        "owned by a deleted object, or objects removed as a side effect. Pods do not count.",
        "criteria": {"true": "some other object of those kinds is deleted",
                     "false": "no object of those kinds is deleted besides the command's own target(s)"}},
    "restart_breaks": {
        "type": "boolean",
        "instructions": "Two minutes after the command, if one pod of each remaining Deployment and StatefulSet were "
                        "deleted, would any of the replacement pods fail to become ready within a minute?",
        "criteria": {"true": "at least one replacement pod would not become ready within a minute",
                     "false": "every replacement pod would become ready within a minute"}},
}
QKEYS = list(QUESTIONS)

# Key (hidden-consequence) question per family: the answer the twin variable is designed to flip.
KEY_QUESTION = {"F1_ns_delete": "data_lost", "F2_template_labels": "outage", "F3_immutable_apply": "fails",
                "F4_apply_prune": "deletes_unnamed", "F5_replace_force": "deletes_unnamed",
                "F6_noexecute_taint": "pods_terminated", "F7_quota_scale": "replicas_short",
                "F8_configmap_delete": "restart_breaks", "F9_cascade": "pods_terminated",
                "F10_sts_pvc_retention": "data_lost"}


def _tokens(command: str) -> list:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def select_rules(command: str, files: dict | None = None) -> list:
    """Rule ids for one command line (+ the files it reads), by command form only."""
    t = _tokens(command)
    words = [w for w in t[1:] if not w.startswith("-")]
    verb = words[0] if words else ""
    rest = " ".join(t[1:])
    target = (words[1] if len(words) > 1 else "").split("/")[0].lower()
    ftxt = "\n".join((files or {}).values())
    out = []

    def add(*ids):
        for i in ids:
            if i not in out:
                out.append(i)

    if verb == "delete":
        if target in ("namespace", "namespaces", "ns"):
            add("K1_namespace", "K2_reclaim", "K9_cascade", "K3_service")
        elif target in ("statefulset", "statefulsets", "sts"):
            add("K9_cascade", "K13_sts_pvc", "K2_reclaim", "K3_service")
        elif target in ("deployment", "deployments", "deploy", "replicaset", "replicasets", "rs", "daemonset",
                        "daemonsets", "ds", "job", "jobs"):
            add("K9_cascade", "K3_service")
        elif target in ("configmap", "configmaps", "cm", "secret", "secrets"):
            add("K12_configmap")
        elif target in ("persistentvolumeclaim", "persistentvolumeclaims", "pvc"):
            add("K2_reclaim")
    elif verb == "scale":
        add("K11_quota")
        if target in ("statefulset", "statefulsets", "sts"):
            add("K13_sts_pvc", "K2_reclaim")
    elif verb == "apply":
        add("K6_immutable", "K4_rollout")
        if "--prune" in rest:
            add("K7_prune", "K9_cascade", "K3_service")
    elif verb == "replace":
        add("K8_replace", "K6_immutable", "K4_rollout", "K9_cascade")
        if re.search(r"(?m)^kind:\s*Namespace\b", ftxt):
            add("K1_namespace", "K2_reclaim", "K3_service")
    elif verb in ("patch", "set", "label", "edit", "rollout"):
        add("K4_rollout", "K5_strategy", "K3_service")
    elif verb == "taint":
        add("K10_taint", "K3_service")
    return out


def rules_for_pair(commands_and_files) -> list:
    """Union of select_rules over the scenarios of a twin pair, in the fixed ORDER."""
    ids = set()
    for cmd, files in commands_and_files:
        ids.update(select_rules(cmd, files))
    return [i for i in ORDER if i in ids]


def rule_texts(ids) -> list:
    return [RULES[i][0] for i in ids]


def state_block(summary: dict) -> str:
    """The current state as given to every forecaster: the summary JSON (files included)."""
    return json.dumps(summary, ensure_ascii=False, indent=1)


def ekbasis_prompt(P, version: str, summary: dict, command: str, rule_ids=None):
    """(state, questions) for the Ekbasis client: world layout; with rules, the rules go after the action (notes) and
    are recapped before every question (client 0.1.2+ recap). P = ekbasis.prompts."""
    notes = rule_texts(rule_ids) if rule_ids else None
    state = P.world_state(PREAMBLE.format(version=version), state_block(summary), [command], notes=notes)
    qs = {k: dict(v) for k, v in QUESTIONS.items()}
    if rule_ids:
        qs = P.recap_all(qs, rule_texts(rule_ids))
    return state, qs


def llm_prompt(P, version: str, summary: dict, command: str, rule_ids=None) -> str:
    """The same situation text for Claude, with the same questions, asking for one probability per question."""
    notes = rule_texts(rule_ids) if rule_ids else None
    state = P.world_state(PREAMBLE.format(version=version), state_block(summary), [command], notes=notes)
    qlines = "\n".join(f'- "{k}": {q["instructions"]} (yes = {q["criteria"]["true"]}; no = {q["criteria"]["false"]})'
                       for k, q in QUESTIONS.items())
    return ("You are predicting what a kubectl command will do to a Kubernetes cluster. Read the situation, then give, "
            "for each question, the probability (a number from 0 to 1) that the answer is yes.\n\n"
            f"=== Situation ===\n{state}\n\n=== Questions ===\n{qlines}\n\n"
            "Reply with only one JSON object that maps each question key to its probability, for example "
            '{"fails": 0.1, "pods_terminated": 0.9, ...}, with all seven keys and no other text.')
