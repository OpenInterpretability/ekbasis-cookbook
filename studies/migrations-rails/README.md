# Migration guard for Rails (v6): better than the rules, one criterion missed

*Pre-registered, run 11 October 2026 on the hosted API (Ekbasis-27B-INT4). Plan: [PREREG_v6.md](PREREG_v6.md)
(sha256 in [PREREG_v6.sha256](PREREG_v6.sha256), frozen before any model call). Deviations:
[DEVIATIONS_v6.md](DEVIATIONS_v6.md). The plan and deviations are in Portuguese; this summary is in English.*

## The question

With `framework: rails`, the guard renders each new Rails migration on the base schema and checks the SQL it sends.
Ruby that goes beyond the schema DSL (models, `find_each`, loops) is listed as "code not foreseen, review by hand"
(`on-code: warn`) and does not fail the check. Does the guard pass the same four criteria as the earlier migration
studies (v3, v5)?

## Sample

168 real migrations from two PostgreSQL projects: **Mastodon** (`9e3fab2`, Rails 8.1) and **Maybe** (`77b5469`,
Rails 7.2). Each one was run by Rails itself on a database seeded with synthetic rows; what happened is the label.
Loomio was excluded before the draw, because its oldest migrations cannot be replayed from an empty database.

## Results (on the 140 migrations the guard answers)

| Criterion | Guard | Regex rules on the rendered SQL | Verdict |
|---|---|---|---|
| P1 accuracy | 0.886 [0.829, 0.936] | 0.607 (difference +0.279 [+0.207, +0.357]) | pass |
| P2 reason exact (target ≥ 0.85, Wilson lower bound ≥ 0.75) | 33/40 = 0.825 [0.680, 0.913] | 0.789 | **fail** |
| P3 false alarms on benign migrations | 15/99 = 15.2% | 52.5% (McNemar p < 0.0001) | pass |
| P4 recall | 40/41 = 0.976 | 0.927 | pass |

P2 is an absolute target, not a comparison with the rules; it is the same target as in v3 and v5. By the registered
rule, Rails stays **experimental** (behind `EKBASIS_EXPERIMENTAL_RAILS=1`).

The seven wrong reasons:
- five in Maybe: the guard said "may fail" for migrations that only lose data (dropping a column or a table);
- two in Mastodon: migrations that need Redis, which the isolated generator does not have, so the guard could not
  foresee them.

Reported without a target: 28 of 168 migrations (16.7%) hold Ruby the guard does not foresee; 9 of them were truly
risky. Counting those as missed, recall over all risky migrations is 40/50 = 0.800.

Cost: 587,905 input tokens; median model time 0.88 s.

## What came next

A v7 adds a throwaway Redis to the isolated generator and a rule decided in code for migrations whose statements depend
only on the schema and that already ran on it. It is pre-registered on new Rails projects.

## Limits

Two projects, and 34 of the 41 risky migrations come from Maybe. Labels come from synthetic seeded rows, not production
data.

## Files

- `PREREG_v6.md`, `PREREG_v6.sha256`, `MANIFEST_v6.sha256`, `DEVIATIONS_v6.md`
- `results_v6.txt` (the registered analysis output) and `analysis_v6.py`
- `harness_rails.py`, `inner.py`, `ekh_rails.rb`, `convert_v6.py`, `run_v6.py`: the harness that labels by running Rails
  and the runner
