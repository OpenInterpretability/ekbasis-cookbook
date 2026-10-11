# Ekbasis as a merge guard for database migrations

*A pre-registered study, run 2026-10-10 on the hosted API (Ekbasis-27B-INT4). The migrations come from 12 public
repositories. The labels come from running each migration on a seeded PostgreSQL database, never from a model or a
reader.*

## Summary

- **The question.** Can Ekbasis say, before a migration is merged, whether it will **lose data** or **fail**? We do
  not ask whether it can review code in general.
- **The data.** 582 PostgreSQL migrations from 12 open-source projects (Prisma, Diesel, golang-migrate, pop). We
  sampled them from 3,543 using their text only, before any label existed.
- **The labels.** Each migration ran on a database seeded with 20 synthetic rows per table. 170 lost data, 64 failed,
  33 were left half applied.
- **The protocol.** One request per migration with three frozen yes/no questions. "Yes" means P ≥ 0.5. The plan was
  hashed before any model call.
- **Data loss: strong, and better than a good linter rule.** On the 370 migrations that look destructive, AUROC 0.948
  [0.924, 0.968] and F1 0.836. A copy-aware regex reaches F1 0.785. The gain is small (+0.051 [+0.023, +0.081]). It
  comes from fewer false alarms: at the regex's recall, precision goes from 0.671 to 0.805.
- **Failure: much better than the rule.** AUROC 0.963 [0.942, 0.980], F1 0.692 against 0.397 for the rule.
- **Calibration of the loss probability: failed** (ECE 0.142 against a 0.10 threshold).
- **Main weakness.** When a migration fails, Ekbasis still tends to predict that its destructive statement ran: 27 of
  its 61 false alarms on data loss are migrations that fail. AUROC for loss is 0.985 on migrations that run cleanly
  and 0.757 on those that fail.
- **An LLM judge is not distinguishable on 60 items.** GLM-5.3-Flash: AUROC 0.936 vs 0.991 for Ekbasis on loss, and
  F1 0.933 vs 0.906. All CIs cross zero (§5).
- **Follow-up (§7).** Telling the model that a failed file applies nothing did not cut those false alarms (36 → 35
  of 45). The product's state, with planner statistics instead of rows, is non-inferior on loss (AUROC 0.921).
- **Product (§8), on 184 new migrations.** The verdict and reason are decided in code: accuracy 0.875 against 0.696
  for the rules, correct reason on 92.5%, false alarms on benign migrations 15.6% against 43.0%. Every pre-registered
  target passed.
- **Cost.** 4.39 M input tokens for 582 requests ($0.18 at the $0.04 per 1M price at the time). Median 1.9 s of model time per request.

## 1. Design

**Hypothesis.** Ekbasis is useful as a cheap merge guard for consequential changes: migrations that lose data or fail
half applied. It is not tested here as a general code reviewer.

**Why migrations.** The consequence can be measured by running them. No reader decides the label.

**Sources.** The migrations come from 12 repositories, pinned to one commit each. **No migration text is
redistributed here**: `recompute.py --check-sources` downloads the files.

| Repository | Format | License (GitHub) | Items |
|---|---|---|---|
| calcom/cal.com | Prisma | MIT | 59 |
| langfuse/langfuse | Prisma | see repository | 60 |
| triggerdotdev/trigger.dev | Prisma | Apache-2.0 | 60 |
| documenso/documenso | Prisma | AGPL-3.0 | 51 |
| formbricks/formbricks | Prisma | see repository | 58 |
| hoppscotch/hoppscotch | Prisma | MIT | 20 |
| umami-software/umami | Prisma | MIT | 23 |
| LemmyNet/lemmy | Diesel | AGPL-3.0 | 54 |
| rust-lang/crates.io | Diesel | Apache-2.0 | 53 |
| dani-garcia/vaultwarden | Diesel | AGPL-3.0 | 24 |
| mattermost/mattermost | golang-migrate | see repository | 60 |
| ory/kratos | pop | Apache-2.0 | 60 |

**Sample.** We drew the sample from the text alone, per repository, in three strata:
- **A, "looks destructive"**: a broad rule (R2) matches: DROP, TRUNCATE, DELETE, UPDATE, RENAME or ALTER TYPE. Up to
  40 per repository.
- **B, "looks risky"**: NOT NULL, constraints or unique indexes, and R2 does not match. Up to 15.
- **C, "looks benign"**: up to 5.

Size limit: 40 statements and 9,000 characters. 599 were drawn and 17 excluded (§2), which leaves 582.

**Execution.** Local PostgreSQL 16. For each sampled migration:
1. A schema-only database is advanced to the migration just before it.
2. **Empty run.** The migration runs on the schema with no rows. Any error excludes the item: that failure comes from
   the environment, not from the data.
3. **Seed.** 20 synthetic rows go into every table:
   - text and JSON get unique tokens;
   - nullable columns are NULL 25% of the time;
   - foreign keys point at seeded rows.
4. **State.** It is built from the seeded database, before anything runs.
5. **Run.** Statements run one by one in autocommit and continue after an error, as `psql -f` does. A second run in
   one transaction gives secondary labels.

**Labels.**
- `lost`: a non-NULL value stored before is, afterwards, in no table at all. The check tracks values across renames,
  copies and moves.
- `fails`: some statement errors.
- `half_applied`: it fails, and the schema or the data still changed.

The labeler passes 22 hand-written cases in `frozen/test_labels.py`.

**State.** It uses the `world_state` layout of the Ekbasis client, the same as `preflight.check_sql`:
- the rules (PostgreSQL 16, autocommit, a failed statement changes nothing and the next one still runs);
- the DDL of the tables the migration names and of their foreign-key neighbors;
- per table: the row count, 2 sample rows, and NULL counts, repeated values and value counts per column;
- how many rows match each literal the statements compare with;
- then the statements, numbered.

All SQL comments are removed. Prisma writes "All the data in the column will be lost" in its comments, and that would
give the label away. The median state is about 2k tokens.

**Questions** (yes/no, in `frozen/statebuild.py`):
- "Does this migration permanently lose any data …?"
- "Does any statement fail …?"
- "Is it left half applied …?"

**Baselines.**
- **Regex rules:**
  - R1, a typical linter: DROP, TRUNCATE, DELETE without WHERE, RENAME;
  - R2, broad;
  - R3, copy-aware: a DROP is ignored if an earlier INSERT or UPDATE named the column;
  - F1, the failure rule.

  For data loss we compare with R3, the best rule. It was chosen on the same data, which favors the rules.
- **An LLM judge.** GLM-5.3 on 60 fixed items, exploratory (§5).

## 2. Pre-registration

`frozen/PREREG.md` was hashed before any model call (SHA-256 `e20495c5…4384`, 22:39 UTC). `frozen/MANIFEST.sha256`
fixes the code, the sample and the labels. `frozen/PREREG_sha256.txt` logs the two files changed afterwards and when.

**Exclusions:**
- 7 migrations fail on the empty schema;
- 4 name a table that could not be seeded;
- 6 have rows that cannot be traced;
- 2 states are over 8k tokens.

A 20-item pilot checked the pipeline (0 errors). Its answers are kept, as registered.

**Deviations** (`frozen/DEVIATIONS.md`):
- The runner was changed before the pilot, to record queue time and model time separately.
- Registered secondary analyses were coded during the run, before any result.
- **H5 was first computed on all 582 items** (0.093, a pass). The registered population is stratum A: 0.142, a
  failure.
- The synthetic rows are not bit-for-bit reproducible. An independent rebuild changes 2 of 582 labels.

## 3. Results

| | Population | Ekbasis | Best rule | Verdict |
|---|---|---|---|---|
| H1: loss, AUROC ≥ 0.85, lower CI ≥ 0.80 | A, n=370, 170 losses | 0.948 [0.924, 0.968] | R3: 0.776 | **passed** |
| H2: loss, F1 above R3 (paired CI > 0) | A | 0.836 vs 0.785: +0.051 [+0.023, +0.081] | | **passed** |
| H3: failure, AUROC ≥ 0.80 and F1 above the rule | all 582, 64 failures | AUROC 0.963 [0.942, 0.980]; F1 0.692 vs 0.397 | F1 rule: AUROC 0.797 | **passed** |
| H4: half applied (exploratory) | all, 33 | AUROC 0.938; F1 0.447 | H1 rule: F1 0.288 | — |
| H5: loss, ECE ≤ 0.10 | A | 0.142 | | **failed** |

**Data loss in detail** (stratum A):

| | Precision | Recall | F1 |
|---|---|---|---|
| R1 (typical linter) | 0.688 | 0.806 | 0.743 |
| R3 (copy-aware) | 0.671 | 0.947 | 0.785 |
| Ekbasis, P ≥ 0.5 | 0.731 | 0.976 | 0.836 |
| Ekbasis at R3's recall (P ≥ 0.915) | 0.805 | ≥ 0.947 | |
| R3 AND Ekbasis | 0.750 | 0.935 | 0.832 |

**Robustness:**
- **Repository-clustered CI** for H1: [0.913, 0.977].
- **S1**, without losses that depend on how the random foreign keys join: AUROC 0.955, F1 over R3 +0.035
  [+0.010, +0.062].
- **S2**, without migrations that fail casting a synthetic value (a token where real rows hold JSON or an enum label):
  AUROC 0.957, F1 over R3 +0.047 [+0.019, +0.077]. Failure AUROC drops to 0.951.
- **Transactional-runner labels:** AUROC 0.964 for loss and 0.945 for failure.

**Reading.**
- **Strong when the deciding fact is in the state.** Examples: a NULL count before `SET NOT NULL`; a copy that comes
  before a `DROP COLUMN`; an INSERT that will fail on NULLs, followed by a `DROP TABLE` that runs anyway.
- **The regex is already good at "is something dropped?"** Ekbasis adds less there than in "will it fail?", which
  depends on the data.
- **The main error is predicting loss for a failed migration.** For example, `DROP COLUMN` and `ADD COLUMN ... NOT NULL`
  in one `ALTER TABLE` fail together and lose nothing. The preflight notes the same habit: asked about a whole plan,
  the model tends to assume every step works. Asking step by step, as `preflight` does, is the known mitigation. It was
  not tested here.

## 4. Cost and latency

All 582 requests went through the hosted API, one at a time:
- **0 errors.** 4,389,789 input tokens. The server counts the state once per question.
- **Model time** (from `Server-Timing`): median 1.9 s, p90 3.2 s.
- **Gateway queue:** median 1.0 s, p90 4.1 s. Another study shared the queue.

## 5. LLM judge (exploratory)

GLM-5.3-Flash, our production model, at low reasoning. It got the same states and questions, answered with
probabilities in JSON, and ran one request at a time with a 2 s pause. The 60 items were fixed before the run,
stratified by outcome (`frozen/glm_ids.txt`). The subsample is enriched in positives, so its numbers are not
comparable to §3. With n = 60, intervals are wide.

| Same 60 items | Ekbasis AUROC | GLM AUROC | Ekbasis F1 | GLM F1 | Rule F1 |
|---|---|---|---|---|---|
| lost (24 positive) | 0.991 | 0.936 | 0.906 | 0.933 | 0.846 (R3) |
| fails (16) | 0.968 | 0.907 | 0.788 | 0.839 | 0.638 |
| half applied (11) | 0.929 | 0.825 | 0.560 | 0.727 | 0.611 |

- **No difference is distinguishable.** AUROC differences (Ekbasis − GLM) are +0.055 [−0.003, +0.124], +0.061
  [−0.008, +0.151] and +0.104 [−0.038, +0.262]. F1 differences are −0.028, −0.051 and −0.167, all with CIs across
  zero.
- **The GLM's probabilities are coarse.** It used 4 distinct values for `lost` (0, 0.3, 0.95, 1). This costs it in
  AUROC, not in F1 at 0.5.
- **Both beat the rules** on this subsample.
- **Cost.** The GLM read 139k prompt tokens and wrote 5.8k (median 46 reasoning tokens), with a median latency of
  3.7 s. Ekbasis read 462k tokens (each question reads the state) and spent a median of 1.9 s in the model. One is a
  27B consequence model on a hosted API. The other is a large production LLM.

## 6. Limits

- **Synthetic data.** NULLs at 25%, random foreign-key pairs and tokens in place of JSON create failures and losses
  that production data might not have. The labels are true for the database the state describes. S1 and S2 measure
  how much this matters.
- **Autocommit.** Most PostgreSQL tools run each file in one transaction, where "half applied" rarely happens. The
  rule is written in the state, and the transactional labels give the other regime. MySQL, where half-applied
  migrations are common, is not covered.
- **Literal definition of loss.** Overwriting a value or changing it by a cast counts as loss. So does turning a
  boolean into the presence of a row.
- **Rich state.** The guard needs read access to a copy of the database, or to its statistics. A guard that sees only
  the diff has less to go on.
- **Coverage.** Django, Alembic, Rails and migrations written in application code are not covered. Repositories differ
  a lot: mattermost has 2 losses in 60.
- **One hosted INT4 build, one run per item.**

## 7. Follow-up: the guard's own state (pre-registered, 2026-10-11)

The study became a product: `ekbasis migrate-check` and a GitHub Action
([ekbasis PR #10](https://github.com/OpenInterpretability/ekbasis/pull/10)). The product changes the state in two ways:
- **The real runner's rule.** The state says that a file runs as one transaction, so if a statement fails, nothing is
  applied. Files that cannot run in a transaction (60 of 582) keep autocommit rules.
- **Planner statistics instead of rows.** Estimated rows, NULL fraction and distinct counts. No sample rows, no
  values, no literal counts.

The plan (`v2/frozen/PREREG_v2.md`, SHA-256 `ae75a427…f65c`) was hashed before any call. The frozen pipeline
re-executed the 582 migrations. The new states come from the same seeded databases as the new labels; against the
study, 2 `lost` labels differ and no `fails` label does. Labels follow the regime the product states. There are three
arms:
- **v1:** the study's answers;
- **A2:** the product's state;
- **A1:** the study's state with the product's rule, an ablation.

Each arm is one request per item, one at a time, on the hosted API.

| | v1 | A2 (product) | A1 (ablation) | Rule |
|---|---|---|---|---|
| Loss, stratum A: AUROC | 0.931 | 0.921 [0.893, 0.947] | 0.933 | — |
| Loss, stratum A: F1 | 0.809 | 0.803 | 0.818 | R3: 0.768 |
| Loss false alarms on the 45 failing migrations that lose nothing | 36 | 35 | 35 | R3: 35 |
| Loss: ECE | 0.166 | 0.180 | 0.152 | — |
| Failure: AUROC | 0.963 | 0.945 [0.922, 0.964] | 0.966 | — |
| Failure: F1 (recall) | 0.692 (0.844) | 0.637 (0.672) | 0.713 (0.797) | 0.397 |
| Median model time / input tokens per request | — | 1.13 s / 3.2k | 1.82 s / 4.9k | — |

| Hypothesis | Verdict |
|---|---|
| H1: fewer loss false alarms on failing migrations (≤ 0.40, McNemar p < 0.05) | **failed** (0.80 → 0.78, p = 1.0) |
| H2: loss AUROC ≥ 0.90, lower CI ≥ 0.85 | passed |
| H3: loss F1 above R3 | passed (+0.035 [+0.011, +0.060]) |
| H4: failure AUROC ≥ 0.90 and F1 above the rule | passed |
| H5: loss ECE ≤ 0.10 | **failed** (0.180) |
| H6: not worse than v1 on loss AUROC (margin 0.03) | passed (−0.010 [−0.021, +0.002]) |
| H7: the Action end to end (4 PRs, private test repository, rerun at the final commit) | passed |

**Reading.**
- **The rule alone does not fix the main weakness.** The model reads "if any statement fails, nothing is applied", and
  in another question it foresees the failure, but its loss answer does not use that. A1 shows the same with rows in
  the state.
- **Statistics instead of rows cost little on loss.** On failure, recall drops (0.80 → 0.67), because some failures
  depend on values the statistics do not show.
- **The pre-registered decision rule says "not ready"** (H1 failed).

**Post hoc, not registered.** Composing the two answers in code for transactional files,
P(lost) × (1 − P(fails)), cuts those false alarms from 35 to 12. It also misses 18 of 161 losses instead of 4, F1 0.810
and ECE 0.118. A separate pre-registered run would have to test it before the product adopts it.

`v2/answers_v2.jsonl` has, per migration, the labels of the re-execution and the A2/A1 answers. `v2/recompute_v2.py`
recomputes the tables (standard library). `v2/frozen/` has the plan, the manifest, the scripts as they ran and the
outputs.

## 8. The product's verdict on a new sample (pre-registered, 2026-10-11)

After §7, the decision moved into code:
- **Risky** if P(fails) ≥ 0.5, or P(lost) ≥ 0.5, or the migration fails on the base's schema.
- **The reason says "fails"** (with "nothing in the file would be applied" for a transactional file) whenever a failure
  is foreseen, and "loses" only otherwise.
- **The PR also changed security:** migrations run as a throwaway role that is not a superuser, in a container with no
  network.
- **Unchanged:** the questions, the state and the thresholds. The final state text equals the one evaluated in §7 for
  582 of 582 items (`v2/frozen/DEVIATIONS_v2.md`).

**The evaluation.** The plan (`v3/frozen/PREREG_v3.md`, SHA-256 `d70e9afd…c1cc`) was hashed before any call.
- **Sample.** 192 migrations the study never drew, from the same 11 repositories (kratos left out: its pop layout
  splits one migration into several dialect files), with the same sampler, a new seed and the same strata. 8 were
  excluded, which leaves 184.
- **Labels.** They come from the frozen executor, in the regime the product states: 56 risky (21 fail, 35 only lose)
  and 128 benign.
- **The product side ran the product's own code.** The schema was built as the non-superuser role, and planner
  statistics were read from the seeded database.

| Product metric (184 items) | Product | Rules (R3 or F1) | Target | Verdict |
|---|---|---|---|---|
| P1 verdict accuracy, risky vs ok | **0.875** [0.826, 0.924] | 0.696 | ≥ 0.85, lower CI ≥ 0.80, above rules | passed (+0.179 [+0.109, +0.250]) |
| P2 reason exact, on risky items flagged | **0.925** (49/53) [0.821, 0.970] | 0.836 | ≥ 0.85, lower CI ≥ 0.75 | passed |
| P3 false alarms on benign | **0.156** (20/128) [0.103, 0.229] | 0.430 | ≤ 0.20, upper CI ≤ 0.30, below rules | passed (McNemar p < 0.0001) |
| P4 recall on risky | **0.946** (53/56) | 0.982 | ≥ 0.85 | passed |

The pre-registered decision is **ready**.

The Action was run end to end at the same commit:
- 5 pull requests gave the expected verdicts;
- one comment per pull request;
- the key does not appear in the logs;
- a hostile `COPY ... TO PROGRAM` migration was reported as cannot foresee, not run.

**Reading.**
- **The reason fixes what §7 could not.** On migrations that fail, the reason now says so (16 of 19 flagged), and the
  loss-first order of v2 would have been right on 38 of 53 instead of 49.
- **Most of the gain over the rules is fewer false alarms.**
  - Stratum A ("looks destructive", 84): accuracy 0.786 against 0.679. That is where the decisions are hard.
  - Stratum B ("looks risky"): accuracy 0.95 against 0.54.
  - Stratum C ("looks benign"): the rules never fire (1.000), and the product raised 2 false alarms in 37 (0.946).
- **Cost.** 871k input tokens for 184 requests; median model time 1.36 s.

`v3/answers_v3.jsonl` has, per migration: identifiers, labels, the truth, the model's answers, and the product and
rule verdicts. `v3/recompute_v3.py` recomputes P1–P4, and `v3/frozen/` holds the plan and the scripts as they ran.
`v3/frozen/FINAL_CHECK.md` shows that the commit for merge (`e5b606f`) builds the same state text and the same
verdicts as the evaluated one.

## Files

| File | What it is |
|---|---|
| `answers.jsonl` | one line per migration: `id`, `repo`, `commit`, `path`, `file_sha256`, `stratum`, labels, transactional labels, SQLSTATEs, loss mechanisms, rule outputs, Ekbasis P(yes) per question, and GLM P(yes) on the 60 subsample items |
| `excluded.jsonl` | the 17 excluded migrations and why |
| `recompute.py` | every table above from `answers.jsonl` (standard library, seconds). `--check-sources` downloads the migrations at the pinned commits and checks their hashes and the sample; `--execute` re-runs the pipeline on a local PostgreSQL 16 |
| `recompute_output.txt` | its output |
| `frozen/` | the plan, its hash log, the deviations and the scripts as they ran (sampler, executor, labeler, state builder, rules, runners, analysis) |
| `v2/` | the follow-up of section 7: answers, recompute script and frozen plan, scripts and outputs |
| `v3/` | the product evaluation of section 8: answers, recompute script, frozen plan and scripts |

Not released, because they contain third-party code: the requests (states include the statements) and the
per-item execution records. Their hashes are in `frozen/PREREG_sha256.txt` and `frozen/MANIFEST.sha256`.
