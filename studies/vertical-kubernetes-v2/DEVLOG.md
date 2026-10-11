# Dev log (every change to scenarios, labelling, facts, R2 or the guard, in order)

## Infrastructure (no model, no test labels)
- Own kind cluster `vk8s2` (Kubernetes 1.37, kindnet, one node), own outsider container `vk8s2-outsider`, prober image
  `vk8s2-prober:2` (alpine + psql 16, mariadb client + connector-c for caching_sha2, redis-cli, curl, nc). Images of the
  scenarios pre-pulled into the node (`images*.txt`), so rollout timing does not include pulls.
- Real chart archives pulled unmodified into `charts/src` (`charts/SHA256SUMS`); kubernetes.io examples fetched into
  `docs_examples/`.
- v1 fixes, before any v2 label:
  1. helm dry run: an object already in the release is now dry-run as the merge patch from the release manifest to the
     new rendering (`kubectl patch --type merge --dry-run=server`), which removes fields the rendering drops; v1 applied
     the rendered object with `kubectl apply`, which never removes a field, so it accepted the volumeClaimTemplates
     removal the real upgrade rejects. A new object that already exists outside the release is reported as rejected.
  2. down noise: repeated measurement (3 runs when the first longest gap is in [1.0, 4.0] s), median, and a grey zone
     [1.5, 2.5) s excluded and declared.
  3. exposure keyed by channel and port, not by Service name; the other-namespace channel counts only when the
     namespace had an ingress NetworkPolicy before.
- Dev labelling found a runner bug: the pre-seed baseline of a database probe queried the table that the seed creates
  (every DB scenario errored). Fixed (pre-seed probes run `select 1`); dev scenarios re-run. No test label existed.
- s62 (test) values corrected before any test label: bitnami's key is `primary.networkPolicy.*` (not `networkPolicy.*`),
  and the client namespace is allowed with `ingressNSMatchLabels` so the probe passes its baseline.

## R2 development (before any test label)
- R2 (`rule2.py`, using `derived.py`) written from the Kubernetes/Helm documentation; checked on the 75 v1 scenarios
  (v1 facts, v1 label definitions, `r2_on_v1.py`): lost 10/0/0/65 (tp/fp/fn/tn), down 34/2/4/35, exposed 14/0/1/60.
  The 2 down false positives are the v1 helm dry-run bug (s71, s74); 3 of the 4 misses are ~2 s noise items; the
  exposed miss is the v1 Service-name artifact (s75). No change made to R2 because of these.

## Test labelling (18:23–19:31 UTC, then 20:28 UTC)
- Two workers; output printed per item only as "labelled"/"ERROR". s53 and s55 errored in v1 (grafana's cluster-scoped
  ClusterRole collided with the other worker's grafana release); re-run alone, unchanged scenario definitions.
- An earlier launch at 18:12 failed immediately (shell passed the id list as one argument); nothing ran.

## After the PREREG seal (20:34:41 UTC)
- Dev round 1 (answers_dev1, 20:34–20:36 UTC): composite F1 Ekbasis 0.968, R2 1.000, R1 0.741. Ekbasis errors: lost
  false alarms on s1 and s20 (podinfo's emptyDir /data, which holds no stored data), down missed on s17 (slow start, no
  probe; the same miss as v1 s20). None is a state bug, so per the PREREG no second round; guard.py frozen UNCHANGED.
