# Migration guard for Rails (v7): supported from 0.1.21

*Pre-registered, run 11 October 2026. Plan: [PREREG_v7.md](PREREG_v7.md); the code under test changed before any valid
call, recorded in [ADDENDUM_A1.md](ADDENDUM_A1.md) (sha256 in [ADDENDUM_A1.sha256](ADDENDUM_A1.sha256)); deviations,
including 486 calls discarded because they ran on code that would not ship, in [DEVIATIONS_v7.md](DEVIATIONS_v7.md).
Plan, addendum and deviations are in Portuguese.*

## What changed since v6

- A throwaway Redis on the generator's isolated network (`--redis auto`), for projects whose migrations need it.
- A rule decided in code: when every statement of a migration depends only on the schema and it already ran on the
  base schema, it cannot fail because of the rows (v6 had said "may fail" for migrations that only lost data).
- The Rails renderer compared migration versions as strings (versions with a leading zero were skipped).

## Sample

Redmine, OpenProject and Consul Democracy (new projects; Mastodon and Maybe from v6 became development). Each
migration run by Rails on a seeded database; 343 analysed, 307 answered, 119 risky.

## Result (on the code that shipped: 0.1.20 + these changes)

| Criterion | Guard | Regex rules | Verdict |
|---|---|---|---|
| P1 accuracy | 0.896 [0.860, 0.928] | 0.730 (+0.166 [+0.127, +0.208]) | pass |
| P2 reason exact | 118/119 = 0.992 [0.954, 0.999] | 0.966 | pass |
| P3 false alarms on benign | 32/188 = 0.170 [0.123, 0.230] | 0.441 | pass (upper bound above 0.20) |
| P4 recall | 119/119 | 119/119 | pass |
| P5 no regression on the 184 v3 migrations | accuracy 0.897 → 0.902, false alarms 17 → 16, recall 54 → 54 | | pass |

- 0 "cannot foresee" for lack of an external service (2 in v6). 10.5% of migrations hold Ruby the guard does not
  foresee; counting them as missed, total recall is 119/132.
- Caveats: Consul holds 108 of the 119 risky migrations, mostly column removals, and there are only 4 real failures.
  28 of the 32 false alarms are OpenProject data migrations (renames, deduplication); with synthetic rows that have no
  duplicates they change nothing, which may not hold on a real database.
- A rule written from the PostgreSQL documentation with the same facts reached 0.889 on this sample, a tie with the
  guard (see `../migrations-rich-rule/`).

## Files

`PREREG_v7.md`, `ADDENDUM_A1.md`, manifests, `DEVIATIONS_v7.md`, `eval/` (results and the registered analysis),
`p5/` (the no-regression check, with per-item state hashes).

The per-item answers in `eval/preds/` and `p5/preds/` were published without the `server_timing` field (it names an internal component); their hashes therefore differ from the manifests, which hold the originals.
