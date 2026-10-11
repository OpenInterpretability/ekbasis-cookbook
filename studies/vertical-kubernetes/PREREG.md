# Kubernetes change guard — pre-registration (pilot, 2026-10-11)

Written and hashed BEFORE any Ekbasis call. Nothing here is shipped or published.

## Question
Given a state built only from facts read before the change (facts.py: live objects, server dry run, helm render,
volumes, data placement, Service endpoints, NetworkPolicies, RBAC), can Ekbasis predict whether a `kubectl apply`,
`kubectl delete` or `helm upgrade/uninstall` takes a service down, loses data or exposes something, better than a
fixed rule?

## Data
- 75 scenarios WRITTEN BY US (Claude, this session) in `scenarios.py`: Deployments, StatefulSets, PVCs (local-path,
  reclaim Delete and Retain), Services, NetworkPolicies, RBAC, postgres:17-alpine and redis:7 in Deployments and
  StatefulSets, and the bitnami charts postgresql 18.x, redis 25.x and nginx 28.x. One local kind cluster
  (Kubernetes 1.37, kindnet), no cloud account, no real repo. No Ingress (no controller installed).
- **Deliberate design bias:** the brief asked to aim where a rule is blind, so the scenario mix over-weights
  mechanisms the rule below does not encode (Service selector/targetPort, maxUnavailable, single-replica StatefulSet
  with a probe, emptyDir/no-volume data, redis persistence, PVC protection, retention policies, OnDelete/partition,
  dry-run rejections, NetworkPolicy edits, explicit RBAC grants). Results do NOT estimate performance on a natural
  distribution of changes.
- Split: `dev` = ids 1-18 (the state builder, notes and questions may be tuned on them with Ekbasis calls);
  `test` = ids 19-75 (frozen: `scenarios_test.sha256` below hashes their definitions; labels in `labels_test.json`).
- Labels by EXECUTION only (`runner.py`), produced before this file and before any model call:
  - down: a client probe (from another namespace, through the Service DNS name, every 0.2 s; HTTP GET, psql query of
    the seeded table, redis AUTH+PING) whose baseline passed 3/3 has a gap >= 2.0 s between two successes with a
    failure inside it (or fails and does not recover for >= 2.0 s) between the change and settle+5 s (window 20-95 s).
    Borderline: if a gap falls in [1.0, 3.5] s the scenario is run twice more and down is the majority of 3 runs.
  - lost: the seeded token (1,000 postgres rows / a redis key) is found nowhere afterwards: not through the Service
    (after waiting up to 60 s), not in any running pod of the namespace, not in any directory under the node's
    /var/local-path-provisioner (Delete and Retain PVs) or /var/lib/kubelet/pods (emptyDir).
  - exposed: an access that fails before and succeeds after: a Service nodePort or a hostPort reachable from a
    container on the kind docker network; a ClusterIP Service reachable from a pod of another namespace (vk-outside);
    postgres login with no password / redis PING with no AUTH through the Service; `kubectl auth can-i` get/list
    secrets, create pods, create pods/exec in the namespace for the namespace default SA, the vk-outside default SA,
    or an authenticated user.
  - failed: some command exits non-zero (secondary).
- Scenarios whose v1/seed/baseline errored are excluded and listed in `labels_excluded.json`.
- Disclosure: I (the author) saw the dev labels while building the state builder and notes. I did not read the test
  labels per item before the guard freeze (only counts of positives and of errors, below).

## Guard (`guard.py`, frozen by hash before the first TEST call; dev tuning allowed before that)
- State: world layout. Current state of the namespace (workloads with replicas, rollout bounds computed for the
  replica count, readiness probes, commands, env with secrets redacted, mounts; pods with where the postgres data
  directory / redis dir lives and row/key counts, redis save/appendonly; Services with ready endpoints; PVCs with PV
  reclaimPolicy and used size; NetworkPolicies with the pods they select; RBAC and what three identities can do now;
  Secrets by key name only). Actions = the commands with their object-level effects (field diff live -> server dry
  run, or the dry-run rejection; helm values diff and rendered-object diff; objects helm would delete). Derived facts:
  what each Service selector and targetPort meet after the change; whether new images exist in the registry.
  Behaviour notes (Kubernetes/helm/image semantics, one paragraph each) added only when the change type needs them.
- Questions: lost, down, exposed, fails (yes/no, text in guard.py). One request per scenario, concurrency 1.
- Decision in code: risky = any of p_lost, p_down, p_exposed >= 0.5.

## Rule baseline (frozen now: `guard.rule`, hash below; it will not change during dev tuning)
- R_down: a Deployment/StatefulSet whose pod template changes AND (strategy Recreate OR replicas <= 1 with no
  readiness probe); or a delete of a Deployment, StatefulSet, Pod or Service (helm included).
- R_lost: a StatefulSet whose volumeClaimTemplates change; a delete of a PVC whose reclaimPolicy is Delete.
- R_exposed: a Service created as / changed to NodePort or LoadBalancer; hostPort or hostNetwork newly in a pod
  template; a Role/ClusterRole rule newly holding '*'; a (Cluster)RoleBinding newly binding cluster-admin/admin/edit or a
  broad group (system:authenticated/unauthenticated/serviceaccounts[:ns]/anonymous); a delete of a NetworkPolicy;
  auth switched off (POSTGRES_HOST_AUTH_METHOD=trust or ALLOW_EMPTY_PASSWORD=yes newly in env, --requirepass removed
  from args, helm value auth.enabled newly false).
- R_risky = OR. The rule ignores the dry-run verdicts and the live facts (except PV reclaimPolicy).

## Hypotheses (test split only; threshold 0.5 fixed)
- H1 (primary, composite risky): Ekbasis F1 >= rule F1 + 0.05 -> "beats the rule"; |diff| < 0.05 -> "tie"; else
  "loses". Exact McNemar on per-item correctness reported (p < 0.05 to call it significant).
- H2 (per label lost/down/exposed): Ekbasis AUROC >= 0.80 for each label with >= 3 positives; F1 vs rule reported.
- H3 (complementarity): on the (item, label) cells where the rule is wrong, Ekbasis is right on >= 50%.
- H4 (controls): among test scenarios with all three labels false, Ekbasis flags <= 20%.
- Product criterion (decided now): worth pursuing only if H1 = beats AND H4 holds; tie/loses with H3 -> at most a
  second layer behind the rule; otherwise no. Because of the design bias above, even "beats" only says that Ekbasis
  covers mechanisms a simple rule misses on scenarios we chose; it is not an estimate of real-world precision.

## Procedure
1. Dev: `ask.py answers_devN dev` for rounds N = 1..3 at most; between rounds only guard.py state text, notes and
   question wording may change (never the rule, threshold, labels or test scenarios). Every change logged in
   DEVLOG.md. Dev results are reported but are not evidence.
2. Freeze: sha256 of guard.py sent to "main" before the first test call.
3. Test: `ask.py answers_test test`, every labelled test scenario once, concurrency 1. After the freeze only crash
   fixes are allowed (logged), no change to the state text, notes, questions or threshold.
4. `evaluate.py answers_test test`, reported as is.

## Labels as frozen (test split, before any model call)
- Test: 57 labelled, 0 excluded. Positives: lost 6, down 30, exposed 11, failed 4; 18 controls (all three false).
  5 test scenarios went through the borderline down rule (3 runs each).
- Dev: 18 labelled, 0 excluded. Positives: lost 4, down 8, exposed 4, failed 2; 5 controls.
- Test labels were produced with facts.py before its pg_info fix for scenarios other than 70, 71, 72, 75 (those were
  re-run with the fix); the fix only affects pods whose postgres user is not superuser (bitnami), i.e. those four.
- Hashes of the code, the rule, the test scenario definitions and the label files: `PREREG.sha256` (guard.py's hash
  there is the pre-dev version; the frozen version is sent to main before the test run).
- Known label noise: down near the 2 s threshold flips between runs (dev s9: 2.07 s, then 0.0 s on a re-run).
