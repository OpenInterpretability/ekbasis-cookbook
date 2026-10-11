# Migration guard for Django and Alembic: two pre-registered evaluations (v4, v5)

*Run 2026-10-11 on the hosted API (Ekbasis-27B-INT4). These are the studies behind client 0.1.15
([PR #14](https://github.com/OpenInterpretability/ekbasis/pull/14)). The v4 result failed; v5, with the policy
changed, passes for Alembic and fails one criterion for Django, which therefore ships as experimental.*

## Design

**What runs.** The product renders each migration with its own framework inside a container:
- Django uses `sqlmigrate`, through the `migrate` loader;
- Alembic uses offline `upgrade --sql`.

The base schema comes from the framework's own `migrate` and `pg_dump`. `migrate-check --bundle` then checks each
migration's SQL with the state, questions and verdict and reason logic of the PostgreSQL study's v3
([`../migrations/v3/`](../migrations/v3/)).

**Labels.** Each sampled migration is run by its framework (RunPython included) on a copy of the progress database,
seeded with 20 synthetic rows per table. The study's frozen labeler gives `lost`, and the framework's exception gives
`fails`. The truth is: risky = fails or loses. No model and no reader is involved in the labels.

**Criteria** (the same in both plans, per framework, as coded in `analysis_v4.py`):
- P1 accuracy ≥ 0.85, bootstrap lower bound ≥ 0.80, and the bootstrap lower bound of (product − rules) above 0. The
  rules are R3 OR F1 on the rendered SQL.
- P2 the reason is exact in ≥ 85% of the caught risky migrations, Wilson lower bound ≥ 0.75.
- P3 false alarms on benign ≤ 20%, Wilson upper bound ≤ 0.30, below the rules, McNemar p < 0.05.
- P4 recall ≥ 0.85.

## v4 (on-code block), PREREG `1a4e8e38…`, product `af243dd`

The sample was 390 migrations: healthchecks, NetBox and Wagtail (Django), Airflow 2.10.5 and Prefect 3.4.0 (Alembic).

| | Django (235) | Alembic (155) |
|---|---|---|
| P1 accuracy (rules) | 0.762 (0.762), FAIL | 0.884 (0.768), PASS |
| P2 reason | 0.490, FAIL | 0.583, FAIL |
| P3 false alarms (rules) | 0.290 (0.208), FAIL | 0.131 (0.208), FAIL |
| P4 recall | 0.942, PASS | 0.960, PASS |
| Cannot foresee | 30.6% | 12.9% |

**v4 failed.** The cause was the policy: 92 code migrations counted as risky with no reason, and 59 of them were
benign. On the migrations it answered, accuracy was 0.950, the reason was right 95.0% of the time, and false alarms
were 4.3% (exploratory). After this result, `on-code: warn` was chosen as the default. A post-hoc view with code as a
warning instead of a block is in `frozen/fw_eval/results_v4_posthoc.txt`; it is not a registered result.

## v5 (on-code warn), PREREG `9a7f472a…`, product `d96b2ac`, new projects

The sample was 571 migrations: saleor, babybuddy and paperless-ngx (Django), MLflow 3.1.0 and Superset 4.1.2
(Alembic). The sample was extended twice before any model call; both extensions are written into the sealed plan
(section 2). P1–P4 are measured on the migrations the product answers. A migration with code that is not SQL
(RunPython, or an Alembic migration with no offline SQL) is `code_not_foreseen`: listed for review by hand, never
"ok", not blocking.

| | Django (242 answered) | Alembic (141 answered) |
|---|---|---|
| P1 accuracy (rules) | 0.955 (0.826), PASS | 0.986 (0.773), PASS |
| P2 reason | 28/28, PASS | 13/13, PASS |
| P3 false alarms (rules) | 0.024 (0.202), PASS | 0.016 (0.250), PASS |
| P4 recall | 0.824 [0.665, 0.917], **FAIL** | 1.000 [0.772, 1.000], PASS |
| Code not foreseen (review by hand) | 23.7% (24 of 75 risky) | 44.5% (29 of 113 risky) |
| Recall over all risky, review-by-hand = missed | 0.483 | 0.310 |

**Decision** (by the registered rule): Alembic is supported; Django ships as experimental, with a note in its
output.

Read the last row before relying on the guard: counting the migrations sent to review by hand as missed, the guard
alone catches about half of the risky Django migrations and a third of the risky Alembic ones. The rest is code the
guard does not foresee and says so.

**The 6 Django misses:**
- 5 failures from the synthetic values: a smallint out of range, a numeric(5,4) overflow, and a foreign key violated
  by copied rows;
- 1 overwritten `end_date`.

**Product bugs found by the new sample and fixed before the v5 freeze:**
- the Django `sqlmigrate` loader breaks once the squashed files are deleted (paperless-ngx);
- Superset prints to stdout before Alembic's output.

## Limits

- The labels come from synthetic data (20 rows per table, distinct values, NULL at a fixed rate). They measure the
  guard in that world, not on production data.
- One answer per migration, no repetition.
- Ten projects in all, two frameworks; the projects were chosen by us, the migrations were drawn by a seeded sampler.
- There is no deviations file: neither run had a deviation from its plan.

## Recompute

```
python recompute.py
```

Standard library only, a few seconds. It rebuilds the v4 result, the v4 post-hoc view and the v5 result from
`answers_v4.jsonl` and `answers_v5.jsonl`, writes `recompute_output.txt` and compares each with the frozen output.
**All three come out identical** to `frozen/fw_eval/results_v4.txt`, `frozen/fw_eval/results_v4_posthoc.txt` and
`frozen/fw_eval5/results_v5.txt`. The product verdict is recomputed from the decision in code and the two
probabilities; the rule verdict needs the rendered SQL, which is not released, so it is read from the answers file.
The bootstrap comes from [`../migrations/frozen/analysis.py`](../migrations/frozen/analysis.py), the same file the
frozen analysis imported.

## Files

| File | What it is |
|---|---|
| `answers_v4.jsonl`, `answers_v5.jsonl` | one line per sampled migration (411 and 587, exclusions included): `id`, project, framework, path in the upstream repo, file sha256, stratum, exclusion reason, label, decision in code, the model's P(lost) and P(fails) with input tokens and model time, and the product and rule verdicts |
| `recompute.py`, `recompute_output.txt` | the recompute above and its output |
| `frozen/fw_eval/` | v4: `PREREG_v4.md` and its sha256, `MANIFEST_v4.sha256`, the harness, renderer, runner and analysis as they ran, the NetBox config used in the container, the results, and `data/` with the frame, the sample and the labels |
| `frozen/fw_eval5/` | v5: the same, plus the Superset config and the MLflow `alembic.ini` used in the containers |

`shasum -a 256 -c` passes for every released file listed in `PREREG_v*.sha256` and `MANIFEST_v*.sha256` (run it
inside `frozen/fw_eval/` and `frozen/fw_eval5/`; the v5 manifest also lists two v4 files as `../fw_eval/…`, which
resolve). No released file differs from the sealed one.

**Not released**, because they contain third-party code: `data/items/*.jsonl` (the rendered SQL and the state of each
migration), `data/requests_v*.jsonl` (the states sent to the model) and `data/first_build/`. Their hashes are in the
manifests; `shasum -c` reports them as missing. In the answer files the raw `server_timing` header is replaced by
the model time it contained; nothing else is rewritten.

The scripts reference container-internal paths (`/tmp/ekh_inner.py`, `/opt/ekbasis_client`), a disposable PostgreSQL
on `127.0.0.1` with a fixture password, and read the API key from `~/.config/ekbasis/study_api_key` (the path only;
no key is in this repository). They also import two folders of the original workspace: `mgfw` (the ekbasis client at
the commits above) and `pr_study` (the first migrations study, released as
[`../migrations/frozen/`](../migrations/frozen/)). Re-running the pipeline needs both, Docker and the upstream
projects at the pinned versions.
