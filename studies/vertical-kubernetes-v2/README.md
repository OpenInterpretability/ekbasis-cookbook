# Kubernetes change guard v2 — Ekbasis vs a rich rule (not shipped)

**Status:** finished on 2026-10-11. Nothing was published. The kind cluster `vk8s2`, its outsider container and the
prober images were removed.

**Result:** pre-registered outcome H1 = **tie, with R2 numerically better**. On the frozen test split (75 scenarios, 65
of them from real charts or kubernetes.io examples), composite F1 was 0.955 for Ekbasis and 0.991 for R2. That is a
difference of −0.036, with a 95% bootstrap CI of [−0.075, −0.008]. On McNemar, Ekbasis was right alone on 0 items and
R2 on 4 (p = 0.125). The pre-registered decision is that Ekbasis serves at most as a second layer behind R2. H3 shows
this layer adds almost nothing:
- "R2 AND Ekbasis" = 0.991, the same as R2;
- "R2 OR Ekbasis" = 0.955, the same as Ekbasis.

The v1 gap (+0.24 over the simple rule) came from facts the simple rule did not use. Once a rule reads the same
facts, the gap disappears. **Kubernetes is not a product candidate for Ekbasis; R2 is the guard.**

## Question
Given the same facts read before the change, does Ekbasis predict better than a rich documentation-based rule (R2)
whether a `kubectl apply`, `kubectl delete`, `helm upgrade` or `helm uninstall` takes a service down, loses data or
exposes something? It is run as a test of Ekbasis against R2.

## What changed from v1
- **R2 (`rule2.py` + `derived.py`):** written from the Kubernetes and Helm docs and frozen by hash at 18:12 UTC. This
  was before any test label and any call. It reads the same facts and derived facts as the Ekbasis state:
  - the effective change after dry-run verdicts (helm applies the others and deletes nothing if one object is
    rejected);
  - the pods replaced and the minimum ready during the rollout (Recreate, maxUnavailable, StatefulSet one-at-a-time,
    partition, OnDelete, missing image);
  - Service selector, targetPort and ports before and after;
  - NetworkPolicy reachability for the client namespace and for an arbitrary namespace;
  - new RBAC grants;
  - where each data directory lives and what happens to its pod and PVC (reclaimPolicy, protection, retention,
    helm-managed PVCs).
- **Scenarios:** 95 new ones; the 75 v1 scenarios were dev only.

  | Test origin | Count | What it is |
  |---|---|---|
  | real-upgrade | 18 | `helm upgrade` between consecutive releases whose image changes, same values |
  | real-values | 22 | documented values changes |
  | real-uninstall | 7 | `helm uninstall` |
  | real-docs | 18 | kubernetes.io examples and commands, with declared adaptations |
  | written | 10 | written by us |

  The real charts are podinfo, groundhog2k postgres/redis/mariadb, grafana, and bitnami postgresql/redis (images
  from bitnamilegacy).
- **The three v1 problems were fixed before any label:**
  1. **helm dry run.** Each release object is dry-run as the merge patch from the release manifest to the new render,
     so removing volumeClaimTemplates is now rejected, as in reality (dev s10 and test s61: both fail, and R2 and
     Ekbasis both predict fails).
  2. **down noise.** If the first run's longest gap is in [1, 4] s, the scenario runs 3 times and the median is used.
     A grey zone of [1.5, 2.5) s is excluded. No test item fell in it.
  3. **exposure.** It is keyed by channel and port, not by Service name. The other-namespace channel counts only if
     the namespace already had an ingress NetworkPolicy.

## Data and labels
Labels come from execution on kind (Kubernetes 1.37, one node, local-path), with images pre-pulled, as in v1. The
search for the token now also covers mysql, mariadb and grafana, plus hostPath.

| | Lost | Down | Exposed | Failed | Controls |
|---|---|---|---|---|---|
| Test (75) | 12 | 39 | 13 | 2 | 21 |
| Of which real-origin (65) | 11 | 33 | 11 | 2 | |
| Dev (20) | 4 | 12 | 3 | 1 | 4 |

Failed has too few positives for a claim. 0 items were excluded and 0 were grey.

## Pre-registration
- **PREREG:** `PREREG.md` sha256 is `b98dfa20…`. It was sealed at 20:34:41 UTC, before any call.
- **Hashes:** `PREREG.sha256` holds the hashes of the code, R2, the test scenarios and the labels.
- **R2 freeze:** `R2_FREEZE.sha256`. Both were sent to main.
- **Dev:** one round, composite F1 Ekbasis 0.968, R2 1.000. The errors were not state bugs, so guard.py was frozen
  unchanged (`GUARD_FREEZE.sha256`, `f92096bd…` = the PREREG hash) and sent to main.
- **Test:** one run at concurrency 1 (20:36–20:40 UTC), 75/75 with 0 errors. Median latency was 3.5 s and a state was
  about 6.7k input tokens.

## Results (test, `answers_test/metrics.json`, `eval_test.log`)

| | Ekbasis F1 | R2 F1 | R1 F1 (v1 rule) | Ekbasis AUROC | McNemar vs R2 (Ekbasis only / R2 only) |
|---|---|---|---|---|---|
| risky (H1) | 0.955 | **0.991** | 0.667 | 0.980 | 0 / 4, p = 0.125 |
| lost | 0.774 | **1.000** | 0.333 | 0.986 | 0 / 7, p = 0.016 |
| down | **0.987** | 0.974 | 0.644 | 0.999 | 1 / 0 |
| exposed | 1.000 | 1.000 | 0.750 | 1.000 | 0 / 0 |

- **H1:** −0.036, a tie by the ±0.05 margin. The CI excludes 0 in R2's favour.
- **H2 passes:** AUROC is 0.986, 0.999 and 1.000. The ranking is near-perfect; the 0.5 threshold is what fails on
  lost.
- **H3, 1/2:** R2 makes only 2 cell errors.
  - s58 down: grafana adminPassword change, gap 2.81 s. Both R2 and Ekbasis missed it.
  - s75 down: the guestbook redis has no probe. R2 called it slow to start, but it was not. Ekbasis was right.
- **H4 passes, at the limit:** Ekbasis raised 4 false alarms on 21 controls (19.0%). R2 raised 0.
- **Breakdown (exploratory), composite F1:**

  | Subset | Ekbasis | R2 |
  |---|---|---|
  | real-origin (65) | 0.947 | 0.989 |
  | written (10) | 1.000 | 1.000 |
  | real, without podinfo (55) | 0.988 | 0.988 |

- **Where Ekbasis loses:** all 7 of its lost errors (and its 4 false alarms) are podinfo. podinfo mounts an emptyDir
  at /data for its certificate, and Ekbasis reads "pod replaced + emptyDir" as data loss: lost 0.86–0.92 on
  s21–s28 and s30. This is the same false alarm it raised on dev s1 and s20. Under the PREREG it could not be fixed
  after dev, because it was not a state bug.

## What this means
- On real changes, once a rule gets the same derived facts, nearly every outcome is decided by documented mechanics
  that code can apply exactly. Examples:
  - maxUnavailable and the replica count;
  - StatefulSet delete-before-create;
  - emptyDir vs PVC and the reclaimPolicy;
  - NetworkPolicy and RBAC evaluation.
- Ekbasis matches R2 on down and exposed. It loses on lost by over-reading "emptyDir" when nothing is stored there.
- The value v1 measured lived in the derived facts, not in the model. This repeats the dbt pilot: a documentation rule
  given the same facts wins or ties.
- Pre-registered decision: tie, so at most a second layer. H3 and the AND/OR results show that layer adds nothing
  measurable here. My recommendation is not to pursue Kubernetes as an Ekbasis vertical; derived.py + rule2.py are
  the useful artefact.

## Limits
- n = 75. Positives: lost 12, exposed 13, failed 2.
- One node, local-path, no cloud, Ingress, HPA, CSI or load. Images were pre-pulled, so pull time is not in the
  outages.
- R2 was written by the same author who designed the scenarios and labels, and who knew the v1 failure modes. It was
  frozen before the test labels, but R2 and the test share one author's view of Kubernetes. A third-party rule or
  third-party scenarios would be a stronger test.
- 10 of the 75 test scenarios are written by us. The 18 docs scenarios carry small adaptations (declared per
  scenario).
- s58's down label rests on one run (see `DEVIATIONS.md`).

## Files
- **Scenarios and labelling:**
  - `scenarios.py` — the scenarios, with their origin and adaptations;
  - `runner.py` — labelling;
  - `facts.py` — the facts read before the change;
  - `kube.py` — kubectl and helm helpers;
  - `charts/src` + `charts/SHA256SUMS` — the real chart archives;
  - `docs_examples/` — the kubernetes.io examples.
- **The contenders:**
  - `derived.py` — the shared derived facts;
  - `rule2.py` — R2;
  - `guard.py` — the Ekbasis state and questions, plus R1;
  - `ask.py` — the Ekbasis calls;
  - `evaluate.py` — the evaluation;
  - `check_dev.py`, `r2_on_v1.py` — the dev checks.
- **Labels and pre-registration:**
  - `labels_{dev,test,excluded}.json` — the labels;
  - `PREREG.md(.sha256)`, `PREREG.sha256`, `R2_FREEZE.sha256`, `GUARD_FREEZE.sha256` — the pre-registration and
    freezes;
  - `DEVLOG.md`, `DEVIATIONS.md` — the change log and deviations.
- **Outputs:**
  - `answers_dev1/`, `answers_test/` — the answers, with the state, R2 and R1 per item;
  - `runs/s*/` — the facts, manifests and result per scenario;
  - `*.log` — the logs.
