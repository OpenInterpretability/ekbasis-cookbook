# Kubernetes change guard v2 — pre-registration (2026-10-11)

Written and hashed BEFORE any Ekbasis call. Nothing here is shipped or published.

## Why a v2
The v1 pilot (`../vert_k8s`) had Ekbasis beat a simple rule (composite F1 0.937 vs 0.697), with two weaknesses:
(1) all 75 scenarios were written by us, aimed at the rule's blind spots; (2) the Ekbasis state carried derived facts
(Service selector/targetPort matches, NetworkPolicy matches, the dry-run verdict) that the rule did not use. In the dbt
pilot a documentation-based rule beat Ekbasis. v2 asks whether that happens here.

## Question
Given the same facts read before the change, does Ekbasis predict better than a RICH rule (R2) whether a
`kubectl apply`, `kubectl delete`, `helm upgrade` or `helm uninstall` takes a service down, loses data or exposes
something?

## Contenders
- **Ekbasis**: state built by `guard.py` (world layout) from `facts.py` + `derived.py`; questions lost, down, exposed,
  fails (`ekbasis.prompts.yes_no`, `instructions` field); one request per scenario, concurrency 1; risky = any of
  p_lost, p_down, p_exposed >= 0.5.
- **R2** (`rule2.py`, primary comparison): written from the Kubernetes and Helm documentation, in good faith, and
  frozen by hash (`R2_FREEZE.sha256`, 2026-10-11 18:12:18 UTC, sent to main) BEFORE any test label and any Ekbasis
  call. It reads exactly the facts the state is built from and the same derived facts (`derived.py`: effective
  change after dry-run verdicts, pods replaced and minimum ready pods during the rollout, Service selector/targetPort/
  ports before and after, NetworkPolicy reachability for the client namespace and for an arbitrary namespace,
  new RBAC grants, where each data directory lives and the fate of its pod and PVC). It covers immutable fields
  (dry-run rejections), strategy and maxUnavailable, StatefulSet one-at-a-time replacement, readiness, PVC
  reclaimPolicy and protection, volumeClaimTemplates and retention, Service selector/targetPort/ports/type,
  NetworkPolicy, RBAC and auth switches. Its rules are listed in its docstring.
- **R1**: the v1 rule, unchanged (`guard.rule`), as a reference.
- Disclosure: R2 was developed on dev material only — the 75 v1 scenarios (`r2_on_v1.py`) and the 20 new dev
  scenarios (`check_dev.py`). I knew the v1 failure modes when writing it. PDBs are not used by R2 (documented as not
  affecting rollouts).

## Data
- 95 NEW scenarios (`scenarios.py`); none of the 75 v1 scenarios is in the test (they are development material).
  - dev: ids 1–20 (state/notes/R2 developed on them; Ekbasis may be called on them, one round).
  - test: ids 21–95, 75 scenarios, frozen by hash in `R2_FREEZE.sha256` (`scenarios_test.json`) before labelling.
- Test origins: real-upgrade 18 (helm upgrade between consecutive releases of real charts whose image changes, same
  values), real-values 22 (documented values changes of real charts), real-uninstall 7, real-docs 18
  (kubernetes.io examples and commands; adaptations declared per scenario: probe Service added, per-namespace
  hostPath/PV/ClusterRole names, amd64-only images replaced), written 10. **65 of 75 are real-origin.**
- Real charts: podinfo 6.7.1–6.15.0, groundhog2k postgres 1.4.11–1.6.1 / redis 1.3.11–2.4.8 / mariadb 4.3.7–4.4.9,
  grafana 10.1.4–10.5.15, bitnami postgresql 16.7.26/27 and redis 21.2.6/7 (images from docker.io/bitnamilegacy).
  Archives unmodified in `charts/src` (`charts/SHA256SUMS`).
- Cluster: local kind `vk8s2` (Kubernetes 1.37, kindnet, one node, local-path), images pre-pulled. No cloud account.

## Labels (by execution only, `runner.py`, produced before this file and before any model call)
- **down**: client probe (namespace vk-probe, through the Service DNS name, every 0.2 s: HTTP GET, TCP connect,
  psql/mysql query of the seeded table, redis PING) with a gap >= 2.0 s between successes containing a failure (or
  never recovering), from the change until settle + 5 s (20–160 s). **Repetition**: if the first run's longest gap is
  in [1.0, 4.0] s, two more runs; the measure is the MEDIAN longest gap. **Grey zone** [1.5, 2.5) s => down = null,
  excluded from the down label and from the composite unless lost or exposed is true.
- **lost**: the seeded token (1,000 rows postgres/mysql, a redis key, a grafana dashboard) is found nowhere afterwards:
  not through the Service (after waiting up to 90 s), not in any running pod, not in any file under the node's
  local-path directories, emptyDirs or /mnt/vk (hostPath).
- **exposed**: an access that fails before and succeeds after, keyed by channel and PORT (a renamed Service exactly as
  reachable as the old one is not new): Service nodePort / hostPort from a container outside the cluster; a ClusterIP
  port from a pod of another namespace, counted ONLY if the namespace had an ingress NetworkPolicy before; the
  scenario's database/cache answering without credentials; `kubectl auth can-i` get/list secrets, create pods,
  create pods/exec for the namespace default SA, the vk-outside default SA, any authenticated user.
- **failed** (secondary): some command exits non-zero.
- Labelling errors (v1/seed/baseline failures) are excluded and listed in `labels_excluded.json`.

## Labels as frozen (before any model call; per-item test labels not read)
- Test: 75 labelled, 0 excluded. Positives: lost 12, down 39, exposed 13, failed 2; 21 controls (all three false);
  down grey zone 0; 3 items went through the repeated measurement. Real-origin items only (65): lost 11, down 33,
  exposed 11, failed 2. failed has too few positives for any claim (reported only).
- Dev: 20 labelled, 0 excluded. Positives: lost 4, down 12, exposed 3, failed 1; 4 controls.
- Two test items (s53, s55, grafana) first errored in v1 setup because the other worker was installing a grafana
  release with the same cluster-scoped ClusterRole name at the same time; they were re-run alone, unchanged. Logged.

## Hypotheses (test split; threshold 0.5 fixed)
- **H1 (primary)**: composite risky F1, Ekbasis − R2 >= +0.05 → "beats R2"; |diff| < 0.05 → "ties"; else "loses".
  Reported with a 95% bootstrap CI (10,000 resamples of items) and the exact McNemar test on per-item correctness.
- **H2**: Ekbasis AUROC >= 0.80 for each of lost, down, exposed (labels with >= 3 positives).
- **H3 (complementarity)**: on the (item, label) cells where R2 is wrong, Ekbasis is right on >= 50%.
- **H4**: on test controls (all three labels false), Ekbasis flags <= 20%.
- Exploratory: "R2 AND Ekbasis" and "R2 OR Ekbasis" (composite and per label); R1; fails AUROC; per-origin breakdown
  (real vs written).
- **Decision (fixed now)**: if H1 = beats R2 (on these majority-real scenarios) and H4 holds → Kubernetes becomes a
  product candidate, the second vertical after migrations. If H1 = ties → Kubernetes serves as a second layer behind
  R2 (with H3 telling whether that layer adds anything). If H1 = loses → R2 alone; no Ekbasis product for Kubernetes.

## Procedure
1. Dev: `ask.py answers_dev1 dev` (one round; at most one more if a state bug is found, logged). Between rounds only
   guard.py's state text, notes and question wording may change; never R2, derived.py, the threshold, the labels or
   the test scenarios. Changes logged in DEVLOG.md.
2. Freeze guard.py by sha256, sent to main before the first test call.
3. Test: `ask.py answers_test test`, every labelled test scenario once, concurrency 1, 429 → wait. After the freeze
   only crash fixes (logged).
4. `evaluate.py answers_test test`, reported as is.

## Hashes
`PREREG.sha256` holds the hashes of the code, R2, the test scenarios and the label files at the seal.
