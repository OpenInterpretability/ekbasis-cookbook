# `read_once` in the migration guard: narrowly fails the accuracy criterion (negative result)

Pre-registration `PREREG.md` (sha256 `6ff71ad1…`), frozen on 2026-10-11 at 15:04 UTC, before any scored call. The
occurrences are in `DEVIATIONS.md`, the numbers in `results.txt` and the drift in `drift.txt`.

## Question

The migration guard asks 2 or 3 questions about the same state, and the server reads the state once per question. With
`read_once=True`, the server reads the state once for all of them. The question: does the verdict stay non-inferior,
and does the cost fall by at least 35%?

## Design

* **Items:** the 184 migrations of v3 (128 benign and 56 risky), with the frozen labels. The states are those of the
  current product (`3bf2769`, identical to those of `8071e38`).
* **Regimes:** N (no replica, the Action's default) and R (with replica statistics).
* **Arms:** SEP (`ask(state, qs)`, as today) and ONCE (`ask(state, qs, read_once=True)`). Questions and verdict are
  those of the product.
* **Run:** hosted API, concurrency 1, 736 calls between 15:04 and 16:33 UTC. Order shuffled with a seed and arms
  interleaved per item. Zero errors.
* **Decision:** both regimes must pass all criteria.

## Result

| | Criterion | N (the Action's default) | R (replica) |
|---|---|---|---|
| C1 | Paired 95% CI of the accuracy ONCE − SEP, lower bound ≥ −2 pp | −0.54 pp **[−2.72; +1.63]**: **fails** | 0.00 [0.00; 0.00]: passes |
| C2 | False alarm ≤ SEP + 3 | 18 against 19: passes | 20 against 20: passes |
| C3 | Recall ≥ SEP − 2 | 52 against 54: passes, **at the limit** | 54 against 54: passes |
| C4 | Exact reason ≥ SEP − 2 | 48 against 46: passes | 50 against 49: passes |
| C5 | Median of \|Δp\| ≤ 0.05 | 0.003: passes | 0.003: passes |
| G1 | Drop in median usage ≥ 35% | **47.1%** (3,282 → 1,736): passes | **48.6%** (4,172 → 2,143): passes |

**Pre-registered decision: fail.** No PR.

C1 is demanding on purpose: with n = 184, one item is worth 0.54 pp. The point loss is 1 net item (3 items lost
against 2 gained). The result does not show that `read_once` is worse; it shows that these 184 items are not enough to
state that it is not.

## Where it diverges

* **Only in regime N, and only on the `fails` question.** The median of \|Δp\| is 0.003, but the tail is long: 18 of
  378 answers change by more than 0.1 and 8 change by more than 0.3 (maximum of 0.80, on `fails`). On `lost`, the
  maximum \|Δp\| is 0.07.
* **ONCE lowers P(fails) in borderline cases.** The 5 verdicts that change in N:

  | Item | Label | SEP P(fails) | ONCE P(fails) | Effect |
  |---|---|---|---|---|
  | calcom `custom_inputs_type_enum` | fails | 0.755 | 0.392 | **risky missed** |
  | langfuse `add_in_app_agent_run_lifecycle_fields` | loses data | 0.706 (P(lost) 0.08) | 0.363 | **risky missed** (SEP caught it, but for the wrong reason) |
  | lemmy `create_reply_materialized_view` | benign | 0.531 | 0.156 | false alarm removed |
  | mattermost `000200_add_rank_to_attribute_view` | benign | 0.531 | 0.281 | false alarm removed |
  | mattermost `000051_create_msg_root_count` | benign | 0.378 | 0.531 | new false alarm |

  The two losses are the kind of error that costs the most in a guard: risky migrations that pass as ok.
* **With the replica (R), no verdict changes.** Only the reason changes, on 5 items (3 in favor of ONCE and 2 against).
* **Calibration does not get worse.** The AUROC of `fails` goes from 0.971 to 0.980 (N) and from 0.965 to 0.976 (R).
  The Brier of `fails` falls from 0.048 to 0.037 (N). On `lost`, AUROC and Brier stay the same. The damage is
  concentrated in a few items near the threshold, and it does not show up in the aggregate metrics.
* **Base noise:** today's SEP against the v4 SEP, on the same states, had a maximum \|Δp\| of 0.18 (N) and 0.11 (R),
  with **0** verdicts changed. The changes of 0.4 to 0.8 from ONCE are not repetition noise.

## Gain left on the table

* **Input tokens:** −47% (N) and −49% (R) in the median per item. In total, 677 k → 347 k (N) and 843 k → 427 k (R).
* **Latency:** the median of the client's clock falls from 5.1 s to 3.0 s (N) and from 5.0 s to 3.4 s (R). In model
  time from Server-Timing, it falls from 3.8 s to 1.8 s (N).

## Reading

The result is consistent with the ekbasis README, which records −0.9 to −3.1 pp in the rules worlds. Here the point
loss is −0.5 pp, smaller, but it lands on two false negatives. Turning `read_once` on by default would save about half
of the tokens, at the cost of a measured risk of missing 2 of 56 risky migrations in the no-replica regime.

**Paths this study did not test** (each would need a new pre-registration):
* `read_once` only with a replica (regime R), where no verdict changed;
* `read_once` as a client option, off by default;
* a larger set, to narrow the CI.

## Caveats

* **One answer per arm and per item,** with no repetition.
* **Synthetic labels** (the same as v3/v4): they measure that world, not production.
* **`p_half` (10 items) is not part of the verdict.** Its numbers are descriptive only.
* **TS-Bench and AgentDojo were left out** (see PREREG, section 3).

## Artifacts

* `PREREG.md` / `PREREG.sha256`, `DEVIATIONS.md`.
* `compat/`: the declared compatibility check.
* `run.py`, `analyze.py`: frozen (sha256 in the PREREG).
* `ans/answers.jsonl`: 736 answers, with `usage`, Server-Timing and request id.
* `results.txt`, `drift.txt`.
* `ekbasis/`: clone at `3bf2769`. The local branch `migration-guard-read-once` has an **uncommitted** draft of the
  change (default on, `EKBASIS_READ_ONCE=off`, cache key and tests). It was prepared during collection and **did not
  become a PR**, because the criterion failed.
