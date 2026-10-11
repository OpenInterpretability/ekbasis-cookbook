# AWS plan guard on LocalStack — pre-registration (pilot, 2026-10-11)

Written and hashed BEFORE any Ekbasis call. Nothing here is shipped or published. Follows the parked Terraform pilot
(`../tf_guard`, a tie with the rule at +0.047 against a +0.05 margin) and fixes what its README pointed at.

## What changed from the Terraform pilot
- Provider notes: only behaviour VERIFIED BY EXECUTION in this LocalStack (`notes.py`: each note lists the
  provider-behaviour scenarios s901–s919 that prove it; `fidelity/check_notes.py` passes 19/19). The pilot's wrong note
  (DROP DATABASE refused with open sessions) is the failure this prevents.
- Facts that decide persistence are collected by code (the pilot's Redis gap): object and version counts, versioning,
  force_destroy in the state, item counts, deletion protection, messages waiting, secret status / versions / who wrote
  the current value, parameter version and whether its value was changed outside OpenTofu, S3 object content vs the
  state (md5), and whether a name the plan creates is already taken (the pilot's create_before_destroy conflicts).
- Development and test are separate; the test labels are frozen by hash here, the guard code is frozen by a second
  hash (FREEZE.sha256, sent to "main") before any test call.

## Environment and safety
- LocalStack Community `localstack/localstack:4.14.0` (the last image that runs without an auth token; `latest` needs
  a license), OpenTofu 1.13.1, hashicorp/aws 6.68.0. Endpoints forced to http://127.0.0.1:4566, credentials
  "test"/"test", dead proxy for every other host; `fidelity/no_aws_check.py`: 124/124 provider requests to
  127.0.0.1:4566, none elsewhere.
- Fidelity (`fidelity/README.md`): LocalStack Community does NOT enforce IAM, bucket policies, the public access block
  or function URL auth -> EXPOSURE IS NOT LABELLED in this pilot (declared, not worked around). Not used either: the
  SQS 60 s re-create rule (not reproduced), lifecycle expiration, TTL deletion, PITR.

## Data
- 84 change scenarios WRITTEN BY US (Claude, this session) in `scenarios.py`: S3 (buckets, versioning, objects, policy,
  public access block), DynamoDB, SQS, SNS, Secrets Manager, SSM, Lambda, IAM, and mixed plans. No real repo, no
  real account.
- Split fixed by id before any label was seen: dev = id % 3 == 0 (28), test = the rest (56).
- Labels by EXECUTION only (`runner.py`): apply v1, seed data as an application would (20 objects, 200 items, 30
  messages, a secret value, a parameter value, or an overwrite of a managed object), plan v2 and read live facts,
  apply the saved plan while probing by name every 0.2 s (one thread per probe), then search for the seeded data.
  - lost: some seeded datum can no longer be read or restored anywhere in the scenario (any bucket and object version,
    any table, any queue, a secret's AWSCURRENT/AWSPREVIOUS including a secret restored from scheduled deletion, any
    parameter's history).
  - down: a probe by name that passed 3/3 before (head_bucket, describe_table, get_queue_url, get_topic_attributes,
    get_secret_value, get_parameter, invoke) fails at least once during the apply or within 3 s after; OR the apply
    log shows a destroy-then-create replace that keeps a probed name and whose destruction completed (the name did
    not exist for an interval; `runner.replace_gaps`). Added BEFORE any model call because LocalStack deletes and
    creates some resources instantly: s24 and s25 gave down = true in the first labelling run and false in the
    second (0.2 s probes missed the gap). It changed s24, s25, s70 to down = true (`relabel_gaps.py`); in AWS a
    same-name destroy-then-create cannot be gap-free.
  - failed: tofu apply exits non-zero (secondary).
- Scenarios whose v1, seed or plan errored are excluded (`labels_excluded.json`), and so are apply failures caused by
  LocalStack rather than the plan (AWS supports the operation): s28 only (a GSI added to an on-demand table — LocalStack
  never reports it, the provider times out).
- Before freezing, a bug in the labeller was fixed and all DynamoDB scenarios re-run: two seeded tables used the same
  token, so s83 hid the loss of one table (found by reading the result, before any model call).
- Disclosure: the scenarios, the notes and the rule were written by us knowing the scenario families; the notes were
  written after the provider-behaviour runs s901–s919 (never asked to the model), which share families with the
  dev/test scenarios. Notes state general provider behaviour, never a per-scenario answer.

## Guard (`guard.py`, `notes.py`, `facts.py`)
- State: world layout; current state from the plan's prior_state + live facts; actions from resource_changes
  (actions, action_reason, replace_paths, changed attributes, secret strings hidden); notes only when a change type
  needs them.
- Questions: lost, down, fails (yes/no, text in guard.py). One request per scenario, concurrency 1, wait on 429.
- Decision in code: risky = p_lost >= 0.5 or p_down >= 0.5.

## Rule baseline (frozen now: `rule.py`)
- R_lost: delete or replace of a resource that holds data (aws_s3_bucket, aws_s3_object, aws_dynamodb_table,
  aws_sqs_queue, aws_secretsmanager_secret(_version), aws_ssm_parameter).
- R_down: delete or destroy-before-create replace of a resource used by name (the same + aws_sns_topic,
  aws_lambda_function).
- R_risky = R_lost or R_down. (R_exposed — Principal "*" or a removed public access block — is computed, not evaluated.)

## Development phase (dev split only)
- Up to 3 versions of the state builder / notes / question text, each asked on the whole dev set
  (`answers_dev_v1`, `_v2`, `_v3`), judged on dev metrics only. Allowed: state text, which facts are shown, notes
  (only with a passing proof in check_notes.py), question wording. Not allowed: threshold, decision rule, labels,
  rule.py, the split.
- Then FREEZE.sha256 (guard.py, notes.py, facts.py, ask.py, evaluate.py) is written and its hash sent to "main"
  BEFORE the first test call. The test set is asked ONCE (`answers_test`), pilot-free, every labelled test scenario.

## Hypotheses (test split, threshold 0.5 fixed)
- H1 (primary, composite risky): Ekbasis F1 >= rule F1 + 0.05 -> "beats the rule"; |diff| < 0.05 -> "tie"; else
  "loses". McNemar exact on per-item correctness reported (p < 0.05 needed to call it significant).
- H2 (per label lost/down): Ekbasis AUROC >= 0.80 each; F1 vs rule per label reported with the same margin.
- H3 (complementarity): on the (item, label) cells where the rule is wrong, Ekbasis is right on >= 50%.
- H4 (false alarms): among test scenarios with lost and down both false, Ekbasis flags <= 20%.
- Secondary, exploratory: "rule AND Ekbasis" and "rule OR Ekbasis" on the composite (F1, false alarms); fails AUROC.
- Product criterion (decided now): a vertical only if H1 = beats AND H4 holds; if tie/loses but H3 holds, at most a
  second layer behind the rule; otherwise, no.

## Labels as frozen (before any model call)
- dev: 28 labelled; lost 7, down 13, failed 2; 14 with lost and down both false.
- test: 55 labelled (s28 excluded); lost 14, down 20, failed 9; composite risky 21; 34 controls (lost and down false).
- Per item (L = lost, D = down, F = failed, - = none):
  - dev: s3:D s6:F s9:LD s12:L s15:- s18:- s21:- s24:LD s27:LD s30:- s33:- s36:- s39:F s42:D s45:LD s48:LD s51:D
    s54:- s57:D s60:- s63:- s66:LD s69:- s72:- s75:D s78:D s81:- s84:D
  - test: s1:F s2:LD s4:F s5:LD s7:F s8:- s10:- s11:- s13:- s14:- s16:- s17:- s19:- s20:LD s22:LD s23:F s25:D s26:F
    s29:- s31:LD s32:F s34:- s35:- s37:D s38:- s40:LD s41:LD s43:- s44:- s46:- s47:- s49:- s50:L s52:- s53:D s55:D
    s56:LD s58:LD s59:DF s61:- s62:- s64:D s65:LD s67:- s68:- s70:LD s71:- s73:D s74:- s76:- s77:- s79:- s80:- s82:LDF
    s83:LDF
- Noted, not changed: s35 (hash key type S -> N) plans as a no-op — the provider ignores the type change — so it is a
  control. Probe resolution: a same-name replace that completes in milliseconds is caught only by the replace-gap
  clause, not by the probe.
- Hashes of every file the labels and the rule depend on, and of the initial guard code: `PREREG.sha256`.
