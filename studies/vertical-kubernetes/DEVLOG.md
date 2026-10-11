# Dev log (every change to scenarios, labelling, facts or guard, in order)

## Before any Ekbasis call
- Labelling infrastructure built on dev 1-4, 6-10 (no model involved).
- s16 (dev) changed: the v2 values file was `{}`; helm 3 then REUSES the previous values, so nothing changed. Now it
  sets only replicaCount. The helm note was corrected accordingly (it first said previous values are never reused —
  the same kind of error as the Terraform pilot's wrong note).
- Seed: CHECKPOINT moved to a separate, optional statement (the bitnami app user is not superuser).
- Probe loop: each scenario's loop now carries its own marker so two labelling workers can run in parallel.
- Test labelling started at 10:27 local with `scenarios.py` sha256 9b8f3818...; its output is not read per item.
- facts.py: pg_info no longer needs superuser (data_directory falls back to PGDATA from the pod env). Test scenarios
  70, 71, 72, 75 (bitnami postgresql) were collected with the old code and are re-run (labels and facts) after the
  first pass; dev 17 likewise. Dev 1 and 9 are re-run under the borderline rule (introduced after they ran); dev 5
  had never been run.
- guard.py: kubectl's "missing last-applied annotation" warning stripped from dry-run messages; NetworkPolicy
  after-change fact added.

## After the PREREG seal (14:43 UTC)
- Dev round 1 (answers_dev1): 18/18 correct on every label (composite F1 1.00 vs rule 0.38). No guard change
  made after it; no further dev rounds. guard.py frozen unchanged (same hash as in PREREG.sha256).
