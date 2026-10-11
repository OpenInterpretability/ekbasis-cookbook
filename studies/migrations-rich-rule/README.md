# Migration guard: Ekbasis 0.1.20 against a rich rule with the same facts (not published)

**Status:** finished on 2026-10-11. Nothing was published, there was no push and no new call to Ekbasis.

**Result:** the rich rule ties with Ekbasis or wins. **The model adds nothing beyond the facts** (H1 rejected in all
variants).
- **Pre-registered primary** (the frozen R_RICH; v3, 184 migrations, regime R): accuracy 0.880 for Ekbasis and 0.946 for
  the rule. Δ = −6.5 pp, 95% CI [−12.0; −1.6], McNemar 6/18, p = 0.023. Outcome: "the rule is better".
- **Requested sensitivity** (the rule WITHOUT the heuristics that reflect the seeding; post hoc addendum, see below):
  0.880 against 0.913. Δ = −3.3 pp, CI [−7.6; +1.1], McNemar 5/11, p = 0.21. The rule's numerical advantage is not
  significant. **This is the version that holds for the product.** Reading: a tie in practice, and the model does not
  win.

The gain that the migration guard showed against linter rules (0.696) came from the **facts** in the state, not from
the model, as in the Kubernetes and dbt pilots.

## Question
Does a rule written from the PostgreSQL documentation, receiving the same structured facts that the Ekbasis state
shows, tie with it in predicting whether a migration **fails** or **loses data**? The facts are the catalog, the
replica statistics (reduced to what the state prints), the probes, the transaction mode and the statements.

## Pre-registration
- **PREREG:** `PREREG.md`, sha256 `63c08894…`, sealed at 20:46 UTC, before any line of the rule.
- **Frozen rule:** `RULE_FREEZE.sha256` (rule.py `f4c21f4d…`, facts.py, run.py and score_v4.py; file hash
  `e994deaf…`), at 20:55 UTC, before the v3 labels were opened.
- **Predictions:** `PRED_FREEZE.sha256` (`0309a5f1…`, identical in R and N), hashed before scoring.
- **EKB arm:** the p2 composition, that is, the same one that gave 162/184 in `results_p2.txt`. The alternative
  composition (ans_t2 + p2) enters as a sensitivity. The reason is in PREREG §2: the schema-cut states differ from
  those of p2 in 183 of 184 items.
- **Verdict:** p2's `verdict()` with no change. The 2 `fails_code` items in R are equal in both arms.

## The rule (`rule.py`, `facts.py`)
The rule simulates the migration statement by statement over a model of the tables it reaches: rows, NULLs, non-null
values, copies made by the file itself and enum labels present. Then it applies the documented semantics:
- **failure:**
  - ADD COLUMN NOT NULL without DEFAULT on a table with rows;
  - SET NOT NULL or PRIMARY KEY over NULLs;
  - UNIQUE over repeated values (constant DEFAULT, count of distinct values);
  - FOREIGN KEY validated over values not copied from the key;
  - casts that need to parse (text to json, uuid, number or enum; enum without a label present);
  - INSERT…SELECT that takes NULL to a NOT NULL column;
  - DELETE of referenced rows with NO ACTION;
  - FK column set to a literal;
- **loss:**
  - DROP TABLE/COLUMN of values not copied before;
  - DELETE and TRUNCATE;
  - UPDATE that overwrites values;
  - casts that change the value (change of type family, smaller precision, timestamp to date);
- **transaction:** a failure undoes everything. In autocommit, the failing statement changes nothing and the rest
  holds.

Development: 3 rounds on D2 (522 scorable items from v1). Accuracy was 0.885 → 0.929 → 0.964 → 0.966.

**Honest caveat.** Rounds 1 and 2 tuned the rule to dev, which includes hypotheses about which rows a WHERE reaches:
- a specific literal in a free-text column matches no row in the UPDATE, but matches in the DELETE;
- deduplications find no duplicates;
- LOWER/TRIM/REPLACE or an expression that starts from the value itself do not count as an overwrite.

This reflects in part how the database was seeded. This is why the result was checked against v0, the rule written
from the documentation alone and with no tuning (table below, exploratory).

## Results on T2 (`results.txt`)

| Regime R | Accuracy | Recall | False alarm | Exact reason |
|---|---|---|---|---|
| EKB 0.1.20 | 0.880 (162/184) | 0.964 (54/56) | 0.156 (20/128) | 50/54 |
| **R_RICH** | **0.946 (174/184)** | 0.911 (51/56) | **0.039 (5/128)** | 50/51 |
| R_RICH AND EKB | 0.940 | 0.875 | 0.031 | 46/49 |
| R_RICH OR EKB | 0.886 | **1.000 (56/56)** | 0.164 | 52/56 |

| Regime | Δ acc (EKB − rule) | 95% CI | McNemar (EKB only / rule only) | Pre-registered outcome |
|---|---|---|---|---|
| R (primary) | −6.5 pp | [−12.0; −1.6] | 6 / 18, p = 0.023 | the rule is better |
| N | −6.0 pp | [−11.4; −1.1] | 6 / 17, p = 0.035 | the rule is better |
| R, sensitivity (ans_t2) | −4.3 pp | [−8.7; +0.0] | 5 / 13, p = 0.096 | the rule is better |
| N, sensitivity | −6.0 pp | [−10.9; −1.1] | 5 / 16, p = 0.027 | the rule is better |

In the sensitivity, 1 item (mattermost/000137) has no answer in ans_t2 and counts as an EKB error.

**Exploratory: rule versions on T2 (R).**

| Version | Accuracy |
|---|---|
| v0, documentation only | 0.902 |
| after round 1 | 0.962 |
| after round 2 | 0.946 |
| frozen | 0.946 |

**Even with no tuning on dev, the rule already ties with or beats Ekbasis** (Δ = −2.2 pp). Round 2 made the test worse
by 1.6 pp: the fine tuning to dev did not generalize, and the outcome does not depend on it.

## Where each one errs (R)
- **Ekbasis errs by false alarm.** There are 20 alarms against 5 for the rule. The rule is right on its own on 16
  benign items marked "loses" or "fails". Examples:
  - remove_brand_colours_default, enable_pbac_globally, user-following, rework_desktop_tokens;
  - enum cast with no missing label;
  - views and indexes on tables with no conflict.

  These are cases where the model sees DROP, UPDATE or CAST and flags it, without checking in the state whether there
  was an affected value, row or label.
- **The rule errs by recall.** It misses 5 risky items and Ekbasis misses 2. The 4 that Ekbasis gets right on its own:
  - custom_inputs_type_enum and availability_start_and_end_time_as_time (cast failures that the rule does not model);
  - drop_instant_meeting_webhook_trigger and remove_tokens (losses by DELETE with a literal, which the rule treats as
    present only in part);
  - fix_post_aggregates_featured_local (self-referencing UPDATE that the rule treats as "keeps").
- **Both err on 4 benign items.** Both flag loss on deletions or deduplications that, in the seeded database, find no
  row.
- **Complementarity:**
  - "OR" takes recall to 56/56, but inherits Ekbasis's false alarm (16.4%);
  - "AND" stays below the rule alone.

  Ekbasis only adds as an extra recall alarm, at the cost of 4× more false alarms.

## Addendum 1: sensitivity without the seeding heuristics (`ADDENDUM_1.md`, `results_noseed.txt`)
The addendum was requested after I had already scored: the v3 labels were already open. The addendum was sealed at
20:58 UTC (sha256 `53bfdda4…`), before running the variant, with a single criterion: every decision that resolves row
values (which the state does not show) by assuming the seeder becomes the conservative reading, "it may happen". Six
heuristics come out:
1. a literal in a free column does not match in the UPDATE;
2. deduplication finds no duplicates;
3. a JSON condition does not match;
4. a subquery filtered by a literal does not match;
5. LOWER/TRIM/REPLACE/jsonb_set/append on the column itself counts as "kept";
6. threshold n < 32 in varchar shortening.

The variant was frozen in `rule_noseed.py` (`NOSEED_FREEZE.sha256`) and was not tuned after running.

| Regime R | Accuracy | Recall | False alarm | Δ (EKB − rule), 95% CI | McNemar |
|---|---|---|---|---|---|
| EKB 0.1.20 | 0.880 | 0.964 (54/56) | 0.156 (20/128) | | |
| R_RICH frozen | 0.946 | 0.911 (51/56) | 0.039 (5/128) | −6.5 pp [−12.0; −1.6] | 6/18, p = 0.023 |
| **R_RICH_NOSEED** | **0.913** | 0.929 (52/56) | 0.094 (12/128) | **−3.3 pp [−7.6; +1.1]** | 5/11, p = 0.21 |
| NOSEED OR EKB | 0.886 | 1.000 | 0.164 | | |
| NOSEED AND EKB | 0.908 | 0.893 | 0.086 | | |

- **Other NOSEED cuts:**
  - regime N: −2.7 pp [−7.1; +1.6];
  - ans_t2 sensitivity, R: −1.1 pp [−4.9; +2.7], the only case that falls in the "tie" band;
  - ans_t2 sensitivity, N: −2.7 pp;
  - on dev, NOSEED gets 0.914 (false alarm 39/322).
- **Without the heuristics, 7 of the rule's 16 wins become shared false alarms.** Examples: remove_brand_colours_default,
  enable_pbac_globally, migrate_legacy_styling_fields, backfill_score_source. These are precisely the cases where a
  literal UPDATE **would match rows in a real database**. There, Ekbasis's "false alarm" is probably not false in
  production: it is an artifact of the synthetic label. Part of the frozen rule's advantage was this artifact, as had
  been suspected.
- **Even so, the pre-registered criterion never favors the model.** H1 required Δ ≥ +2 pp with CI > 0, and Δ is
  negative in all variants.

## What this means for the product (with NOSEED, as requested)
- **A tie in practice, with the rule numerically ahead** (0.913 against 0.880, no significance). The model adds no
  accuracy beyond the facts that the pipeline itself builds. This repeats Kubernetes v2 and dbt: **the value of the
  migration guard is in the facts pipeline** (cut catalog, statistics, probes, transaction simulation).
- The evidence does not support announcing "the model predicts what a rule does not". What holds:
  1. the product is the facts pipeline plus a deterministic verifier;
  2. Ekbasis comes in at most as a second opinion for recall, in warning mode: "OR" reaches recall 56/56, but with 16%
     false alarm;
  3. or the model is trained not to alarm without evidence in the state.
- Because the labels come from a seeded database, neither accuracy is the production one. A fair comparison with real
  databases needs labels from real incidents (T1 of p2/v4, n = 4 to 6, too small) or a real replica. That is outside
  this pre-registration.

## Limits
- n = 184 and 56 risky; the CIs are wide (from 1.6 to 12 pp).
- The labels come from a seeded database (20 rows, random values). Part of the rule's advantage, and of the hypotheses
  from its dev set, depends on that distribution. In production, a literal matches rows more often.
- The rule's predictions are identical in R and N: on this data, the replica statistics changed nothing in it.
- The rule was written by one author, with access to the labels and mechanisms of v1. It is an author's "best good-faith rule"
  and not an upper bound.

## Files
- `PREREG.md`, `PREREG.sha256`, `RULE_FREEZE.sha256` and `PRED_FREEZE.sha256`;
- `facts.py` (the only door to the data), `rule.py` (the frozen R_RICH), `run.py` and `score.py`;
- `results.txt` and `preds/`;
- `dev_round1.log`, `dev_round2.log` and `dev_final.log`;
- `rule_v0.py`, `rule_r1.py` and `rule_r2.py` (snapshots for the ablation);
- `ADDENDUM_1.md`/`.sha256`, `rule_noseed.py`, `NOSEED_FREEZE.sha256`, `score_any.py` and `results_noseed.txt`.
