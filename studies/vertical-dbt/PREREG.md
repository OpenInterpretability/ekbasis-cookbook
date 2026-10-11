# PREREG: Ekbasis as a guard for dbt changes (DuckDB)

Written 2026-10-11, before any call to the Ekbasis API. Its SHA-256 is sent to `main` before the first call.

## Question

Before a dbt change runs (an edited model, `--full-refresh`, an incremental or snapshot edit, a materialization change),
can Ekbasis say whether it will **(a) lose data** held in incremental models or snapshots, **(b) break the downstream**
(another model, snapshot or test errors or fails), or **(c) fail itself**? It is not tested as a general dbt reviewer.

## Data

**Projects (public, pinned):**

| key | repository | commit | role |
|---|---|---|---|
| jsd | dbt-labs/jaffle_shop_duckdb | 20cc904370818ceab08cf19f8fd196e9e81def88 | dev |
| attr | dbt-labs/attribution-playbook | 54e5543f7fc914f0701c259b83d43be77be519bd | dev |
| mrr | dbt-labs/mrr-playbook | f7921cf7f67e57e8eb1ce86dc16fa3a9e03cee94 | test |
| js3 | dbt-labs/jaffle-shop | 5beb145b00f5465ec759cfcdd9745e858818cf95 | test |

None of the four public projects has an incremental model or a snapshot. **Written by us** (declared):
- Compatibility patches for dbt-core 1.12 + DuckDB (`code/port.py`, marked `compat`): key renames (`source-paths`,
  `data-paths`), `dateadd` → interval arithmetic, `surrogate_key` → `generate_surrogate_key`, a date literal cast, the
  dbt version pin of jaffle-shop, 33 short rows of `sessions.csv`, and attribution test names that no longer matched
  the model's columns.
- **The history layer** in every project: two incremental models (one with `unique_key`, one append-only; mrr has one),
  one snapshot (check strategy), a table that reads the incremental model, a view that reads the snapshot, and tests.
- **The data history**: build, then source changes (updates + new rows; in variant `retained` the oldest rows are also
  deleted from the sources, so they survive only in the history tables), build again, then pending source changes that
  the item's command will pick up. Two warehouse variants per project: `retained` and `intact`.
- **All 420 changes** (`code/mutate.py`, `items_all.jsonl`, SHA-256
  `5b670d3042dd4f403265f33132d340931754bbb96165ce8fd8785c0697fb40dc`). Families: `cmd` (commands without edits),
  `inc` (incremental edits), `snap` (snapshot edits), `col` (remove / rename / cast a column), `model` (delete,
  materialization, row filter, new test), `ctrl` (harmless by design). Items were generated from the project text only.

## Labels (by execution, `code/execute.py`)

Copy the base project and warehouse, apply the change, run `dbt compile` (on a throwaway copy, for the facts), then run
the item's command on the warehouse.
- **lost**: a row of an incremental model or snapshot that existed before (projected on the columns it had, without
  `dbt_valid_to`, compared as text, as a multiset) is absent afterwards; or one of its columns that held a non-NULL value
  is gone; or the relation is gone. Overwritten values count.
- **targets** = nodes whose file, materialization, `unique_key`, `full_refresh` or snapshot config differ between the
  base manifest and the compiled one, nodes that gain a test, and nodes named in `--select`. Decided in code.
- **broken**: a node that is not a target ends in `error` or `fail` (`run_results.json`; tests on a target count).
- **fails**: a target ends in `error`. Undefined (excluded from H3) when there is no target.
- **compile_error**: `dbt compile` of the changed project fails. These items get **no model call**: the verdict is
  decided in code ("does not compile"). They are excluded from H1–H5 and reported apart.

Execution started before this file was written. Before writing it I saw the labels of 22 smoke items and ~40 dev items
(jsd) while debugging the state builder; no test-project label was looked at.

## Facts and state (`code/facts.py`, `code/statebuild.py`)

Structure and counts only, never a data value: the targets with materialization and config before/after, whether the
query has `is_incremental()`, row counts now (current versions for snapshots), columns and types now (catalog), output
columns after the change (static, sqlglot over the compiled SQL), the compiled-SQL diff, the parents with row counts,
the seeds/sources upstream with warehouse and CSV row counts, the children with the columns of the target they name and
whether they `select *`, the tests on the target, the other incremental models and snapshots the command runs, and what
the command selects. Layout: `ekbasis.prompts.world_state` (rules, current state, numbered actions, the standard note).
The rules paragraph includes short dbt notes, chosen in code by what the change touches (full-refresh, incremental,
materialization, snapshot).

**Questions** (yes/no, `noul`; names filled in by code): `lost` ("is any row or value that the incremental models and
snapshots (…) hold now gone …?"), `broken` ("does any model, snapshot or test other than T itself end in error or fail
(tests on T included)?"), `fails` ("does T itself end in error …?", only when T exists). One request per item, all
questions together. "Yes" means P ≥ 0.5.

**Verdict in code**: compile error → "does not compile"; else risky if any of p_lost, p_broken, p_fails ≥ 0.5, with
the reason = the question with the highest p.

## Rules (`code/rules.py`), from the same facts

- **R1, the base rule** (the comparator of H1/H2): lost = `--full-refresh` with an incremental model or snapshot
  selected, or an incremental model/snapshot changes materialization or is deleted, or loses a column. broken = a
  column the changed model no longer outputs is named by a child or a test on it, or a deleted node has a child.
- **R2, a dbt-aware rule** (secondary, reported, no pass/fail): R1 plus the dbt docs (snapshots ignore
  `--full-refresh`; `full_refresh: false`; ephemeral leaves the table; a removed column only drops with
  `sync_all_columns`; a full refresh only loses rows when the table has more rows than its upstream; a `unique_key`
  change or a missing `is_incremental()` filter on a keyed model loses rows; `select *` propagation for broken).

## Split and freezing

- **Dev** = jsd + attr. Allowed changes after seeing dev answers, all logged in `DEVIATIONS.md`: the state builder
  (wording, notes, which facts are shown) and the question wording. Not allowed: labels, rules, split, threshold,
  hypotheses.
- **Test** = mrr + js3. Before the first test call: `TEST_FREEZE.sha256` lists the SHA-256 of the test items, labels,
  states and every code file; its own hash goes to `main`. No change after it.

## Hypotheses (test set, compile errors excluded)

- **H1 lost**: AUROC ≥ 0.80 with 95% CI lower bound ≥ 0.70, **and** F1(Ekbasis) − F1(R1) ≥ +0.05 with the paired
  bootstrap CI lower bound > 0.
- **H2 broken**: same criteria against R1.
- **H3 fails**: AUROC ≥ 0.80 with CI lower bound ≥ 0.70 (no rule comparator).
- **H4 false alarms**: on test items with every label negative, the code verdict alarms on ≤ 15%. Reported also on the
  `ctrl` family and for R1.
- **H5 complementarity**: pooling the `lost` and `broken` decisions, items where R1 is wrong and Ekbasis right outnumber
  items where R1 is right and Ekbasis wrong, exact McNemar p < 0.05.
- A hypothesis with < 10 positives or < 10 negatives in its test population is declared **not evaluable**.

CIs: 2,000 bootstrap resamples **clustered by change** (the item id without its variant, so the two warehouse variants
of one change move together). Reported but not targets: R2 comparisons, ECE (10 bins), per-family results, dev results,
"R1 OR Ekbasis" and "R1 AND Ekbasis".

## Operations

Hosted API (`EKBASIS_URL=https://openinterp.org/api/v1`), client 0.1.16, concurrency 1; on 429 or a long wait, sleep
and retry, never parallel. The key is read from `~/.config/ekbasis/study_api_key` and never printed or saved. Nothing
is published.
