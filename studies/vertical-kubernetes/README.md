# Kubernetes change guard — pilot (not shipped)

**Status:** pilot finished on 2026-10-11. Nothing was published. The cluster and the containers it used were torn down.

**Result:** on the frozen test split, Ekbasis **beats** the rule under the pre-registered criterion. Composite F1 was
0.937 for Ekbasis and 0.697 for the rule, a difference of +0.24 against a +0.05 margin. On the McNemar test, 18 items
were right only for Ekbasis and 3 only for the rule (p = 0.001).

**Caveat:** this does NOT mean the guard is ready for real use. The scenarios were written by us, and they
deliberately over-weight mechanisms the rule cannot see. This was the brief: the Terraform pilot tied, so this one
aimed at the rule's blind spots. The notes were also written while looking at the dev labels. The result shows that
Ekbasis, given these facts and these notes, covers mechanisms that a simple rule misses. It is not an estimate of
precision on real changes.

## Question
Can Ekbasis predict whether a `kubectl apply`, `kubectl delete`, `helm upgrade` or `helm uninstall` will do any of
these better than a fixed rule?
- take a service down;
- lose data on a PVC or volume;
- expose something.

Ekbasis gets a state built only from facts read before the change, plus specific typed questions. The verdict is
decided in code.

## Data
- 75 scenarios, all **written by us** (`scenarios.py`). They run on a local kind cluster (Kubernetes 1.37, kindnet)
  with a single node.
- Workloads:
  - nginx Deployments;
  - postgres:17-alpine and redis:7 in Deployments and StatefulSets;
  - PVCs on local-path, with reclaim policy Delete (`standard`) and Retain (`retain`);
  - Services, NetworkPolicies, PDBs and RBAC;
  - three real bitnami charts: nginx 25.2.1, postgresql 18.12.4 and redis 28.3.1.
- There is no Ingress, because no controller was installed. No cloud account was used.
- Split:
  - **dev**: s1 to s18, used to build the state builder and the notes;
  - **test**: s19 to s75, 57 scenarios frozen by hash before any call.
- Each label comes from **execution**, with no model involved (`runner.py`):
  1. apply v1 and wait until it is ready;
  2. seed a token: 1,000 postgres rows or a redis key;
  3. read the facts;
  4. probe the client endpoints every 0.2 s from another namespace, through the Service DNS name, while v2 runs and
     until the namespace settles (+5 s);
  5. search for the token everywhere: the Service, every running pod, the node's PV directories and the emptyDirs;
  6. re-run the exposure probes: nodePort and hostPort from a container outside the cluster; a ClusterIP Service
     from a pod in another namespace; postgres or redis with no password; `kubectl auth can-i` for three identities.
- down means a gap of at least **2.0 s** between two successful probes. If the gap falls between 1.0 and 3.5 s, the
  scenario is run 3 times and the majority wins. This happened on 5 test scenarios.
- Positives, with 0 scenarios excluded:

  | Label | Test (57 scenarios) | Dev (18 scenarios) |
  |---|---|---|
  | lost | 6 | 4 |
  | down | 30 | 8 |
  | exposed | 11 | 4 |
  | failed | 4 | 2 |
  | controls (all three false) | 18 | 5 |

## Design
- **State** (`guard.py`, built from `facts.py`) uses the world layout. It holds:
  - the namespace now:
    - workloads, with rollout bounds already computed for the replica count, and with probes, command, env (secrets
      redacted) and mounts;
    - where the postgres data directory and the redis dir live, with row and key counts and redis save/appendonly;
    - Services, with their ready endpoints;
    - PVCs, with the PV reclaim policy and the space used;
    - NetworkPolicies, with the pods they select;
    - RBAC, and what three identities can do;
    - Secrets, by key name only.
  - the actions: each command with its effect per object. This is the field diff from the live object to the server
    dry run, or the dry run's rejection. For helm it also covers the values diff, the rendered objects and the
    objects helm would delete.
  - derived facts: what each Service's selector and targetPort match after the change, which pods each NetworkPolicy
    selects, and whether new images exist in the registry.
  - notes on how Kubernetes, helm and the images behave, one paragraph each, added only when the change needs them.
- **Questions:** lost, down, exposed and fails, in one request per scenario, at concurrency 1. The median latency
  was 1.3 s and a state is about 3.7k input tokens.
- **Decision in code:** risky if p ≥ 0.5 for lost, down or exposed.
- **Rule** (`guard.rule`, frozen in the PREREG). It looks only at the change set:
  - down: the template changes and either the strategy is Recreate or there is 1 replica with no probe; or a
    workload, Pod or Service is deleted;
  - lost: the volumeClaimTemplates change, or a PVC with reclaim policy Delete is deleted;
  - exposed: a new NodePort or LoadBalancer; a new hostPort or hostNetwork; RBAC with `*`, a strong role or a broad
    group; a NetworkPolicy is deleted; authentication is turned off.

## Pre-registration
- `PREREG.md` sha256 is `eabd159c5a972fe8b2e5d4b08cd079b0f609d5e1fb3a46731f2ba3baa5a647fa`. `PREREG.sha256` (sha256
  `4ef2cfb9…`) holds the hashes of the code, the rule, the test scenarios and the labels.
- Sealed on 2026-10-11 at 14:43 UTC, before any call. Both hashes were sent to main.
- `guard.py` was frozen at `2523553d5a0771d393de20be081280d750b75a25183069167e955d154c5bd012` and sent to main before
  the test run. This is the same hash as in the PREREG, so nothing changed after the dev round.
- Dev, one round: 18/18 correct on every label. This is optimistic, because the notes were written while looking at
  dev. No more rounds were run.
- Test, one run: 57 items, 0 errors.
- Everything that changed before the seal is in `DEVLOG.md`. One example: the helm note was wrong (see below) and was
  corrected on dev before the seal.

## Results (test, `answers_test/metrics.json`)

| | Ekbasis F1 | Rule F1 | Ekbasis AUROC | McNemar (Ekbasis only / rule only) |
|---|---|---|---|---|
| risky (composite, H1) | **0.937** | 0.697 | 0.927 | 18 / 3, p = 0.001 |
| lost | 1.00 | 0.29 | 1.000 | 5 / 0, p = 0.06 |
| down | 0.90 | 0.62 | 0.928 | 15 / 3, p = 0.008 |
| exposed | 0.95 | 0.78 | 0.996 | 5 / 1, p = 0.22 |

- **H1, beats the rule:** +0.24 against a +0.05 margin.
- **H2, pass:** AUROC is at least 0.80 on all three labels. On fails, AUROC is 0.96.
- **H3, pass:** of the 28 (item, label) cells where the rule is wrong, Ekbasis gets 25 right (89%).
- **H4, pass:** Ekbasis raises 3 false alarms on the 18 controls (16.7%; the limit was 20%). The rule raises 4.
- **Pre-registered product criterion:** "worth pursuing" (H1 beats and H4 holds), subject to the caveat at the top.
- **Sensitivity (exploratory):** without the 5 borderline items, Ekbasis scores 0.944 and the rule 0.721.
- **Where Ekbasis is right and the rule is not:**
  - a selector or targetPort that matches nothing;
  - a named port that was renamed;
  - maxUnavailable at 100%, or maxSurge 0;
  - a single-replica StatefulSet that has a probe (it deletes the pod before it creates the new one);
  - postgres on emptyDir or with no volume;
  - redis with `--save ''` or on emptyDir;
  - a retention policy of whenScaled: Delete;
  - OnDelete;
  - an image that does not exist under RollingUpdate;
  - `trust` on a data directory that is already initialized;
  - pods/exec granted explicitly;
  - `namespaceSelector {}`;
  - verbs `*` on configmaps (not exposure);
  - helm uninstall deletes the NetworkPolicy, but nothing new can be reached.

## Errors and failure modes
1. **Our helm dry run was wrong (s71, s74).** These two set `persistence.enabled: false` in the bitnami chart. In
   reality, `helm upgrade` fails because volumeClaimTemplates are immutable. Our facts simulated the upgrade with
   `kubectl apply --dry-run=server` on the rendered objects. Those objects have no last-applied annotation, so the
   3-way merge does not remove the volumeClaimTemplate and the dry run passes. The state then said "the pod template
   changes, so the pods are replaced". The model followed it: down 0.95, fails 0.01. These are 2 of the 3 false
   alarms. This is the same lesson as the Terraform pilot: a wrong fact or note drags the model with it. The fix is
   to compare the release manifest with the new render, or to use helm's own patch. It was not run.
2. **Slow start with no probe (s20).** The command was `sleep 8; exec nginx`, with 1 replica and no probe. The fact
   was in the state, but the model did not conclude the service would go down (0.18). The rule got this one right.
3. **StatefulSet partition (s42).** With partition 1 and 1 replica, no pod is updated. The note said so, but the model
   predicted down (0.93). The rule also got it wrong.
4. **Label noise at 2 s (s37, s58).** These look like safe rollouts with a probe, but they had gaps of about 2 s from
   the endpoint/termination race (no preStop). The majority of 3 runs gave down. The model said no. The threshold
   cuts through a real, noisy phenomenon. Dev s9 went from 2.07 s to 0.0 s between runs.
5. **An artifact of the exposed definition (s75).** With fullnameOverride, the new Service `maindb` becomes reachable
   from other namespaces, because the chart's NetworkPolicy allows everything. The label counts this as new
   exposure, although the old Service was just as open. The model said 0.09. Under a stricter definition it would
   count as a hit.

## Limits
- n is small: 57 test scenarios, and only 6 positives for lost.
- We wrote the scenarios, the notes, the rule and the label definitions. The mix was chosen for the rule's blind
  spots.
- The state carries derived facts the rule does not use: selector and targetPort matches, NetworkPolicy matches, the
  dry-run verdict and rollout bounds. A richer rule that used them would close part of the gap, and that comparison
  was not made.
- One node with local-path only. No cloud, Ingress, HPA, multiple nodes, real CSI or traffic under load.
- The bitnami charts use rolling `latest` images.

## Files
- `scenarios.py` — the scenarios.
- `runner.py` — labelling by execution.
- `facts.py` — the facts read before the change.
- `kube.py` — kubectl and helm helpers.
- `guard.py` — the state, the questions, the decision and the rule.
- `ask.py` — the Ekbasis calls.
- `evaluate.py` — the evaluation.
- `make_labels.py` — collects the labels.
- `labels_{dev,test,excluded}.json` — the labels.
- `PREREG.md`, `PREREG.sha256` and `GUARD_FREEZE.sha256` — the pre-registration and the freeze.
- `DEVLOG.md` — every change made before the seal.
- `answers_dev1/` and `answers_test/` — the answers, with the state and the rule for each item.
- `runs/s*/` — the facts, the manifests and `result.json` (probes, gaps, accesses) for each scenario.
- `*_label*.log`, `rerun_*.log` and `ask_test.log` — the logs.
