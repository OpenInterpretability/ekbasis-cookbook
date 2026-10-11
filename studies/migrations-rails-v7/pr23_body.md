Rails moves out of `EKBASIS_EXPERIMENTAL_RAILS`. It stays opt-in with `framework: rails`. The PR also carries the two fixes the v6 evaluation pointed to. Rebased on main `4654485` (0.1.20); it becomes **0.1.21** at release, and the CHANGELOG entry is under [Unreleased].

## What changes
- **Throwaway Redis in the generator.**
  - Controlled by `--redis auto|on|off`, or the Action input `redis` (default `auto`, which turns it on when the Gemfile or requirements depend on redis, sidekiq, celery and the like).
  - Isolation: `redis:7-alpine` on the same internal network, which has no route out. No password, no published port, removed at the end. The isolation is described in `docs/MIGRATION_GUARD.md`.
- **"Fails" decided in code when the rows cannot matter** (`migrations.schema_only_plan`). This is shared code, so it applies to every framework and to plain SQL.
  - Condition: the migration ran without error on the base schema, and every statement can fail only because of the schema.
  - Effect: P(fails) is set to 0. The model's value is kept as `p_fail_model`.
  - Order in `_check_file`: probe on the schema → code probes (if they decide, the function returns before the rule) → cut state → model → this rule. The probes cover INSERT, DELETE and UPDATE, which are never schema-only, so the two do not conflict.
- **Rails renderer:** versions are compared as integers. Zero-padded migrations, as in Redmine, used to render nothing.
- **Rails supported, opt-in.** Docs, CHANGELOG, README and the Action's descriptions are updated.

## Pre-registered evaluation (v7 + addendum A1, sha256 `a7e47ed2…4f50`, frozen before any valid call)
The first run, on code older than 0.1.19, was discarded: 486 calls, recorded in DEVIATIONS. These results are on this branch's code.

**Test.** New projects: Redmine, OpenProject and Consul Democracy. The table covers the 307 migrations the guard answers, 119 of them risky. Each migration was run by Rails on a seeded database.

| | Ekbasis | R3∨F1 rules | Target | |
|---|---|---|---|---|
| P1 accuracy | 0.896 [0.860, 0.928], diff +0.166 [+0.127, +0.208] | 0.730 | ≥ 0.85, LB ≥ 0.80, above rules | PASS |
| P2 reason | 118/119 = 0.992, Wilson [0.954, 0.999] | 0.966 | ≥ 0.85, LB ≥ 0.75 | PASS |
| P3 false alarms | 32/188 = 0.170, Wilson [0.123, 0.230]; McNemar p < 0.0001 | 0.441 | ≤ 0.20, UB ≤ 0.30, below rules | PASS |
| P4 recall | 119/119 | 1.000 | ≥ 0.85 | PASS |

**P5: non-inferiority on the 184 SQL migrations of v3.** OLD = main `4654485` (0.1.20), NEW = this branch. One set of fresh answers was used, and the states were asserted byte-for-byte identical (0 of 182 differ).

| | OLD | NEW | Margin |
|---|---|---|---|
| Accuracy | 0.897 | 0.902 | ≥ OLD − 0.02 |
| False alarms | 17 | 16 | ≤ OLD + 3 |
| Recall | 54/56 | 54/56 | ≥ OLD − 2 |
| Reason | 48 | 48 | ≥ OLD − 2 |

P5 **PASSES**.

**Reported separately**
- Reason confusion matrix (truth → said): loses→loses 114, loses→fails 1, fails→fails 4. Two of the four failures were decided by the probes.
- Cannot-foresee from a missing external service: **0**, against 2 in v6.
- Code not foreseen: 10.5% of migrations. Total recall, counting those as missed, is 119/132.

**Caveats**
- P3 is close to its 0.20 bar: 0.170, with upper bound 0.230.
  - 28 of the 32 false alarms are OpenProject data migrations.
  - 10 of those rewrite duplicate names before adding a unique index. The synthetic rows had no duplicates, so nothing was overwritten.
- Consul Democracy holds 108 of the 119 risky migrations, mostly column drops. Only 4 risky migrations failed rather than lost data.
- Exploratory, not registered: without the rule, the same answers give reason 114/119 and the same 32 false alarms. In this sample the rule fixed 4 reasons.

Not merged; that is the lead's call.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
