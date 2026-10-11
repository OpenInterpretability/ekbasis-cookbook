# AWS plan guard on LocalStack — pilot

**Status:** finished on 2026-10-11. Nothing was shipped and nothing was published.

**Result:** a pre-registered **tie** with a simple rule on the primary metric.

| | Ekbasis | Rule | Difference | Margin to "beat" |
|---|---|---|---|---|
| Composite F1 | 0.851 | 0.824 | +0.027 | +0.05 |
| Data-loss F1 | 0.93 | 0.67 | | |

- On data loss, Ekbasis is clearly ahead: McNemar p = 0.004.
- On interruption ("down"), the two tie.
- By the pre-registered product criterion, the guard is **at most a second layer behind the rule**. It is not a
  standalone vertical.

## Question
Can Ekbasis predict what applying an OpenTofu plan to AWS will do better than a fixed rule? The outcomes are data loss
and interruption.

- **Input:** a state built from facts only. Those facts are the plan JSON plus read-only live facts.
- **Questions:** typed questions.
- **Verdict:** decided in code.

Exposure was not evaluated. See Fidelity.

## Environment
- **Software:** LocalStack Community `4.14.0`, OpenTofu 1.13.1, and `hashicorp/aws` 6.68.0.
- **Why 4.14.0:** it is the last Community image that runs without a license. `latest` refuses to start without an
  auth token.
- **No real AWS:**
  - Every endpoint points to 127.0.0.1:4566, and the credentials are "test"/"test".
  - There is no AWS config file or profile.
  - All other traffic goes to a dead proxy.
  - `fidelity/no_aws_check.py` checked this: 124 of 124 provider requests went to 127.0.0.1.
- All containers were removed at the end.

## Fidelity (`fidelity/README.md`)
- **Not faithful, so not labelled — this is the whole exposure label.** LocalStack Community does not enforce:
  - IAM (even with `ENFORCE_IAM=1`);
  - bucket policies or the public access block — an anonymous GET on a private bucket works;
  - auth on Lambda function URLs.
  The IAM and policy scenarios therefore count only as controls for lost and down.
- **Also not faithful, and not used:**
  - the SQS 60 s wait before re-creating a deleted queue name;
  - lifecycle expiration, TTL and PITR;
  - `CreateBucket` on a name you already own in us-east-1.
- **Faithful, used for the labels and checked for every provider note.** This was checked in 19 provider-behaviour
  scenarios (s901–s919), never asked to the model; `check_notes.py` passes 19/19. It covers:
  - BucketNotEmpty, and `force_destroy` read from the *state*, not from the plan;
  - DynamoDB deletion protection, including when the same plan turns it off;
  - ResourceInUse on create_before_destroy with the same name;
  - Secrets Manager scheduled deletion, restore, and the name being blocked;
  - AWSPREVIOUS;
  - SSM history;
  - the S3 object noncurrent version;
  - Lambda staying available during an in-place update;
  - SNS deleting the topic but keeping the queue.
- **Excluded as a LocalStack gap:** s28. LocalStack never reports a newly added GSI.

## Data
- **Scenarios:** 84, all **written by us** (`scenarios.py`). They cover S3, DynamoDB, SQS, SNS, Secrets Manager, SSM,
  Lambda, IAM and mixed changes.
- **Split** (fixed by id): dev is id % 3 == 0, with 28 scenarios. Test has 55 scenarios (s28 excluded).
- **Labelling** (`runner.py`) is done by execution:
  1. apply v1;
  2. seed data as an application would: 20 objects, 200 items, 30 messages, a secret value, a parameter value, or an
     overwrite of a managed object;
  3. plan v2 and read the facts;
  4. apply the saved plan, probing by name every 0.2 s;
  5. search for the data, including object versions, AWSPREVIOUS, restorable secrets and parameter history.
- **"down"** also counts a same-name destroy-then-create replace whose destroy completed. This was added before any
  model call, because s24 and s25 flipped between two labelling runs: LocalStack creates and deletes some resources
  instantly.
- **Test positives:**

  | Label | Positives |
  |---|---|
  | lost | 14 |
  | down | 20 |
  | composite (lost or down) | 21 |
  | apply failed | 9 |
  | controls (no loss, no interruption) | 34 |

## What changed from the Terraform pilot (`../tf_guard`)
- **Notes:** a provider note goes in only if an execution in this LocalStack proves it (`notes.py` → `PROOF`). The
  pilot's failure #1 came from a wrong note about PostgreSQL DROP.
- **Facts the old pilot lacked:** facts that decide persistence are now collected:
  - versioning and noncurrent versions;
  - force_destroy in the state;
  - item and message counts;
  - deletion protection;
  - who wrote the secret's current value;
  - the parameter value differing from the state;
  - the S3 object's md5 against the state;
  - a name the plan creates that is already taken.

## Pre-registration
- `PREREG.md` has sha256 `b2b1fe4c…01acf67`. It was sealed at 14:55 UTC, before any call to Ekbasis.
- `PREREG.sha256` holds the hashes of the code, the rule and the labels.
- Dev phase: one version only (v1, `answers_dev_v1`), with nothing changed.
  - Composite F1 on dev was 0.97 against 0.83 for the rule.
  - The only error was s6: create_before_destroy where the delete of the old bucket fails.
- `FREEZE.sha256` (`a1c226fb…`) holds the same code as the PREREG. It was recorded before the test run.
- The test set was asked once: 55 items, 0 errors, concurrency 1.

## Results (test, `answers_test/metrics.json`, `eval_test.log`)

| | Ekbasis F1 | Rule F1 | Ekbasis AUROC | McNemar (Ek-only / rule-only right) |
|---|---|---|---|---|
| risky (H1) | 0.85 | 0.82 | 0.975 | 4 / 2, p = 0.69 |
| lost | **0.93** | 0.67 | 0.985 | 14 / 2, **p = 0.004** |
| down | 0.82 | 0.79 | 0.956 | 5 / 3, p = 0.73 |

- **H1, tie** (+0.027).
- **H2, pass.** AUROC is at least 0.80 on both labels. On lost, Ekbasis beats the rule by +0.26 in F1. The rule
  flags any delete as loss, and gets 14 false positives.
- **H3, pass.** The rule is wrong on 24 (item, label) cells, and Ekbasis is right on 19 of them (79%). Examples:
  - deletes that fail on BucketNotEmpty or deletion protection;
  - a secret scheduled for deletion, which can be restored;
  - an app value kept as AWSPREVIOUS;
  - interruption on a create_before_destroy rename, which the rule does not see.
- **H4, pass.** On the 34 controls, Ekbasis raises 6 false alarms (17.6%). The rule raises 9.
- **Fails:** AUROC 0.999.
- **Exploratory: combining the two.** "Rule AND Ekbasis" has F1 0.87, with 5 false positives and 1 false negative.
  "Rule OR Ekbasis" has F1 0.81.

## Failure modes
1. **Predicting an interruption when the apply fails first.** This is the same failure as #5 in the earlier pilot. It
   happened on s4 and s7 (and s6 in dev): replace with destroy first, then BucketNotEmpty. The model itself gives
   p_fails ≈ 0.98, yet still predicts p_down ≈ 0.85–0.94. Its answers contradict each other.
2. **"down" measured only on the seeded resource.** This hits s14, s19 and s50. The model predicts down for:
   - an object moved to a new key;
   - an empty bucket that was deleted;
   - a DLQ that was destroyed.
   These are arguably real interruptions for someone, but our probe covered only the seeded resource. **The flaw is
   in the label definition**, and it accounts for 3 of the 6 down false positives.
3. **Partial failure in a mixed plan** (s83). The unprotected table is deleted before the protected one fails. The
   model predicts nothing is lost (p_lost = 0.03) because the apply fails. The note says "if a change fails, only what
   was done before it counts", but it did not apply that.
4. **SQS retention cut to 1 h** (s44). The model predicts loss (0.78) for messages that were minutes old.
5. **s82** (bucket that fails plus a queue destroyed). The model gets the loss right but predicts down = 0.25.

## Limits
- n is small: 55 test items.
- We wrote the scenarios, the notes and the rule ourselves. The notes were written after the fid runs, which share
  families with the test set.
- LocalStack is not AWS: exposure is out, and replace timing differs.
- Probes check only the seeded resource.

## Files
- `scenarios.py`, `runner.py`, `facts.py`, `guard.py`, `notes.py`, `rule.py`, `ask.py`, `evaluate.py`,
  `make_labels.py`, `relabel_gaps.py`, `awsenv.py`.
- `labels_{dev,test,excluded}.json`.
- `PREREG.md`, `PREREG.sha256`, `FREEZE.sha256`.
- `answers_dev_v1/` and `answers_test/`.
- `fidelity/`: the exploration scripts, `check_notes.py`, `no_aws_check.py` and the fidelity README.
- `runs/s*/`: the plan, facts and result for each scenario.
