# Terraform plan guard — pre-registration (pilot, 2026-10-10)

Written and hashed BEFORE any Ekbasis call. Nothing here is shipped.

## Data
- 70 change scenarios WRITTEN BY US (Claude, this session) in `scenarios.py`: Docker containers/volumes (kreuzwerker/docker),
  PostgreSQL objects (cyrilgdn/postgresql) on a local server, local_file/random/null. No cloud account, no real repo.
- Labels by EXECUTION only (`runner.py`): apply v1, seed data, plan v2, read live facts, apply the saved plan while probing,
  then search for the seeded data and re-run exposure probes. Labels (`labels.json`) were produced before this file and
  before any model call; scenarios whose v1/seed/plan errored are excluded (listed in labels_excluded.json).
  - lost: the seeded data is found nowhere afterwards (running container, remaining volume, host dir, any database of
    the scenario, the file).
  - down: an endpoint probe that passed 3/3 before the apply fails at least once during the apply or within 3 s after.
  - exposed: an exposure probe (no-password login, an outsider role with only PUBLIC rights reading the table) fails
    before and succeeds after, or a port is newly bound on all interfaces.
  - failed: tofu apply exits non-zero (secondary).
- Disclosure: the state builder notes were written by us with knowledge of the scenario families and after seeing 4
  trial labels (s1, s21, s41, s66). They state general provider/PostgreSQL/Docker behaviour, never a per-scenario answer.

## Guard (frozen: `tfguard.py`)
- State: world layout; current state from the plan's prior_state + live facts (`facts.py`: docker inspect, volume sizes,
  port answering, pg catalog with exact row counts, ACLs, sessions, extension-typed columns, file vs state content);
  actions from resource_changes (actions, action_reason, replace_paths, changed attributes, secrets redacted); provider
  notes added only when a change type needs them.
- Questions: lost, down, exposed, fails (yes/no, text in tfguard.py). One request per scenario, concurrency 1.
- Decision in code: risky = any of p_lost, p_down, p_exposed >= 0.5; reason from the flags (lost > exposed > down).

## Rule baseline (frozen: `tfguard.rule`)
- R_lost: any delete/replace of a stateful resource (docker_volume, postgresql_database, postgresql_schema, local_file,
  or a docker_container with a database/cache image or any volume block).
- R_down: any delete or destroy-before-create replace of a serving resource (container publishing a port,
  postgresql_database, postgresql_role).
- R_exposed: a planned port on all interfaces not already there; POSTGRES_HOST_AUTH_METHOD=trust newly added; a
  postgresql_grant to public with privileges added.
- R_risky = OR.

## Hypotheses (threshold 0.5, fixed)
- H1 (primary, composite risky): Ekbasis F1 >= rule F1 + 0.05 -> "beats the rule"; |diff| < 0.05 -> "tie"; else "loses".
  McNemar exact on per-item correctness reported (n is small; p < 0.05 needed to call it significant).
- H2 (per label lost/down/exposed): Ekbasis AUROC >= 0.80 each; F1 vs rule reported per label with the same +0.05 margin.
- H3 (complementarity): on the (item, label) cells where the rule is wrong, Ekbasis is right on >= 50%.
- H4 (controls): among scenarios with all three labels false, Ekbasis flags <= 20%.
- Product criterion (decided now): worth a product only if H1 = beats AND H4 holds; if tie/loses but H3 holds, it is
  at most a second layer behind the rule; otherwise, no.

## Procedure
1. Pilot: scenarios 1, 22, 41, 54, 66 (plumbing only: request works, answers parse). Allowed after the pilot: crash
   fixes only, logged; no change to state text, notes, questions or threshold.
2. Full run: every labelled scenario (pilot ones included, re-asked), concurrency 1, `ask.py answers_full`.
3. `evaluate.py answers_full`, reported as is.

## Labels as frozen (before any model call)
- 69 labelled, 1 excluded (s56: our v1 grants on a table that does not exist yet; scenario bug).
- Positives: lost 20, down 38, exposed 5, failed 9; 24 scenarios with all three false (controls for H4).
- Noted, not changed: redis with a named volume or a bind mount still lost the key (s34, s35): the docker provider
  removes the container with force (no graceful shutdown), so redis never wrote its snapshot. Measured truth stays.
