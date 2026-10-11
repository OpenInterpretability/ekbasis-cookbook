# Ekbasis as a guard for dbt changes (pilot, DuckDB)

*A pre-registered pilot, run 2026-10-11 on the hosted API. The changes are made on 4 public dbt-labs projects. The
labels come from running each change with dbt-core 1.12 + dbt-duckdb 1.11 on a seeded warehouse, never from a model
or a reader.*

## Summary

- **The question.** Before a dbt change runs, can Ekbasis say whether it will (a) **lose data** held in incremental
  models or snapshots, (b) **break the downstream**, or (c) **fail itself**?
- **The data.** 420 changes, 4 projects: jaffle_shop_duckdb and attribution-playbook for dev (224), mrr-playbook and
  jaffle-shop for test (196). **None of the four public projects has an incremental model or a snapshot**, so the
  history layer (2 incremental models + 1 snapshot + their downstream per project), the data history and all 420
  changes were **written by us**. Each change runs on two warehouses: `retained` (old rows deleted from the sources
  survive only in the history tables) and `intact`.
- **Protocol.** PREREG hashed before any call (`60e8266a…be87e`); test frozen by hash before the test calls
  (`003dad43…f7a2`); both sent to `main`. One request per item, 3 yes/no questions, "yes" = P ≥ 0.5, verdict in code.
- **Result on test (192 items with a model call, 4 compile errors decided in code):**

| | Ekbasis | R1 (base rule) | R2 (dbt-aware rule) | Verdict |
|---|---|---|---|---|
| H1 lost (30 pos.): AUROC | **0.959** [0.912, 0.996] | | | |
| H1 lost: F1 | 0.675 | 0.486 | **0.806** | **passed** (+0.189 [+0.045, +0.332] vs R1) |
| H2 broken (15 pos.): AUROC | 0.947 [0.902, 0.984] | | | |
| H2 broken: F1 | 0.545 | 0.485 | 0.513 | **failed** (+0.061 [−0.180, +0.320], CI crosses 0) |
| H3 fails (23 pos.): AUROC | 0.860 [**0.693**, 0.984] | | | **failed** (lower bound < 0.70) |
| H4 false alarms, all-negative items (n=126) | 0.294 | 0.310 | | **failed** (target ≤ 0.15) |
| H5 complementarity vs R1 | 63 corrections / 42 regressions | | | **failed** (p = 0.0504) |

- **Reading.** Ekbasis **ranks** risk very well (AUROC 0.95–0.96 for loss and breakage) but **at 0.5 it alarms too
  much**: precision 0.54 for loss and 0.38 for breakage. It beats the naive rule the lead specified (R1), but **loses to
  a rule that encodes the dbt docs** (R2) on data loss by −0.131 F1 [−0.242, −0.041]. On breakage nobody is good:
  Ekbasis 0.545, R1 0.485, R2 0.513.
- **Not ready as a product.** Exploratory: with the threshold chosen on dev (0.95 for loss), test loss is
  P 1.00 / R 0.60 / F1 0.750, which is still below R2 (0.806). Details in §5.

## 1. Design

**Sources (pinned).** dbt-labs/jaffle_shop_duckdb `20cc904`, dbt-labs/attribution-playbook `54e5543`,
dbt-labs/mrr-playbook `f7921cf`, dbt-labs/jaffle-shop `5beb145`. Compatibility patches for dbt 1.12 + DuckDB are listed
in `PREREG.md` and marked `compat` in `code/port.py` (two upstream projects did not build as published: a malformed
CSV and tests naming columns the model no longer has).

**Written by us** (`code/port.py`, `code/mutate.py`): the history layer, the data history (build → source updates,
new rows and, in `retained`, deletions → build → pending source changes picked up by the item's command), and the 420
changes in 6 families: `cmd` (`--full-refresh` on incremental / snapshot / table, plain build), `inc`
(`on_schema_change` × add/drop column, cast, `unique_key`, strategy, `is_incremental()` removed, materialization,
`full_refresh: false`), `snap` (unique_key, strategy, hard_deletes, rename, delete), `col` (remove / rename / cast a
column), `model` (delete, materialization, row filter, new test), `ctrl` (harmless edits).

**Labels** (`code/execute.py`). `lost`: a row of an incremental model or snapshot (projected on its columns, without
`dbt_valid_to`, compared as text) is gone, or a column with values is gone, overwritten values included. `broken`: a
non-target node ends in error or fail (tests on the target count). `fails`: a target errors. Targets are decided in
code from the manifest diff and `--select`.

**Facts** (`code/facts.py`): structure and counts only. Materialization and config before/after, `is_incremental()`
presence, row counts now, catalog columns, output columns after the change (static, sqlglot), compiled-SQL diff,
parents and root seeds/sources with warehouse and CSV row counts, children with the target's columns they name, tests,
the other history tables the command runs. **State** (`code/statebuild.py`): the client's `world_state` layout, with
short dbt notes chosen in code. Median state 3.4k characters.

## 2. Labels on test

| family | none | lost | broken | fails |
|---|---|---|---|---|
| cmd (28) | 16 | 12 | 0 | 0 |
| inc (89) | 53 | 18 (2 also broken) | 2 | 18 |
| snap (22) | 18 | **0** | 0 | 4 |
| col (18) | 7 | 0 | 10 | 1 |
| model (25) | 22 | 0 | 3 | 0 |
| ctrl (10) | 10 | 0 | 0 | 0 |

**No snapshot change lost data**, in dev or in test: `--full-refresh` does not touch snapshots, a deleted or renamed
snapshot leaves its table, and hard_deletes only closes versions. R1 calls several of these losses.

## 3. Where Ekbasis is right and the rules are not

- **Full refresh on an `intact` warehouse.** The incremental table and its source hold the same rows, so nothing is
  lost. R1 flags all of them. Ekbasis mostly does not (cmd family: AUROC 0.96 for loss).
- **`on_schema_change` outcomes.** Dropping a column with `ignore` or `fail` errors, `append_new_columns` runs, and
  `sync_all_columns` drops the column's values. inc family: fails AUROC 0.99, accuracy 0.97. After dev deviation 3,
  the dbt note in the state spells out each option's documented behavior, so this is mostly reading the note.

## 4. Failure modes

1. **Too many alarms at 0.5.** It flags `strategy: append`, a missing `is_incremental()` filter and a `unique_key`
   change as breaking or losing, even when the pending rows do not collide (`broken` P 0.38). At a stricter
   threshold, precision rises and recall falls (§5).
2. **Loss by overwrite is invisible in counts.** In mrr `intact`, a full refresh or `to_table` of `mrr_history`
   recomputes values whose source changed after they were written. Row counts are equal and Ekbasis says p ≈ 0.1. R1
   is right by accident. No count-only fact shows this; it would need a fact like "the upstream changed after these
   rows were written".
3. **Column edits: it mixes up "fails" and "broken".** Removing a column with a downstream consumer is predicted as
   the model's own failure (col family: fails AUROC 0.06 on test, 0.26 on dev). The question names the target, but
   the model does not separate the target from its children.
4. **Unknown-feature failures.** `hard_deletes: new_record` on an existing snapshot errors in this dbt-duckdb (all 4
   test cases, p ≈ 0.01). Nothing in the state hints at it.
5. **Ephemeral / materialization changes** of staging models are predicted to break children (p 0.6–0.9). They do
   not: dbt inlines ephemerals.

## 5. Exploratory (not pre-registered targets)

- **Threshold chosen on dev, applied to test:** loss t=0.95 → P 1.000 / R 0.600 / F1 0.750; broken t=0.925 →
  P 0.700 / R 0.467 / F1 0.560; fails t=0.95 → P 0.833 / R 0.652 / F1 0.732.
- **Combined with rules:** R2 AND Ekbasis for loss, F1 0.812 against R2's 0.806. There is no real gain.
- **Dev (224 items, v4 state):** loss AUROC 0.973, broken 0.948, fails 0.865; false alarms 0.380. These are the same
  pattern as test.
- **Product verdict accuracy** (risky vs safe): Ekbasis 0.766, R1 0.682.
- **Cost:** 192 requests, 0 errors or retries, median 1.73 s (p90 2.97 s) per request.

## 6. Deviations (`DEVIATIONS.md`)

1. **The first dev pass is void.** It sent the question under the key `question`. The API reads `instructions`, so
   every question got the same probability; a control question, "Is the sky green?", scored like the others. Not
   analyzed.
2. **Dev v2 → v3: dbt notes corrected.** `on_schema_change: ignore` errors on a missing column; ephemeral leaves
   the relation.
3. **Dev v3 → v4.** (a) A bug: unquoted compiled SQL in attribution-playbook showed a fake database change. (b) The
   `on_schema_change` note was refined because v3 over-generalized the error.

Also: label execution started before the PREREG was written. 22 smoke labels and ~40 jsd labels were seen first. Two
test log lines were seen in passing before the freeze.

## 7. Caveats

- **The history layer and all the changes are ours**, on toy-sized warehouses (40–30k rows). The public projects
  supply only the base DAG, the SQL and the tests.
- **Items are not independent.** About half the items are pairs (the same change on two warehouses). CIs are
  bootstrapped by change, but 196 items on 2 projects remain a small test.
- **R2 was written by us** with knowledge of dbt. It was registered as secondary, and it was written before the
  labels were seen.
- **Notes in the state carry dbt documentation.** Part of the inc-family score comes from those notes, not from the
  model's own dbt knowledge.
- **One engine** (DuckDB, delete+insert by default). Warehouses with merge or different DDL semantics may behave
  differently.

## 8. Should it become a product?

**Not as a standalone dbt guard.** On loss, a short deterministic rule written from the dbt docs (R2) beats Ekbasis.
On breakage, everything is weak, and the decisive fact (who uses which column, through `select *`) is better resolved
by a real lineage tool (column-level lineage / `dbt compile` + sqlglot) than by a probability. Where Ekbasis adds
something:
- **Ranking.** AUROC 0.95–0.96, useful as a "look here first" score.
- **The `intact` vs `retained` distinction.** Counts decide it, and a rule needs to be written for it.
- **`on_schema_change` and runtime failures,** given the doc notes.

If this vertical is pursued, the next step is a guard with R2 + static lineage in code, with Ekbasis only as a
tie-breaker at a high threshold (≥ 0.9, chosen on dev). It would also need a fact for "upstream changed after the
history was written" (failure mode 2).

## Files

`PREREG.md` (+ `PREREG_sha256.txt`), `DEVIATIONS.md`, `TEST_FREEZE.sha256`, `items_all.jsonl`, `labels_all.jsonl`,
`dev/` (states and answers v2–v4, `results_v4.txt`), `test/` (frozen items/labels/states, `answers.jsonl`,
`results.txt`), `code/` (port, mutate, execute, facts, statebuild, rules, run_ekbasis, analysis, freeze_test).
