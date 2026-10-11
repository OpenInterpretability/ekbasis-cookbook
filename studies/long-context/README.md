# Ekbasis with long state: does the migration guard's verdict survive a 64k-token schema?

*Pre-registered study, run on 2026-10-11 on the hosted API (Ekbasis-27B-INT4).*

* Pre-registration: `PREREG.md`, sha256 `dfbdbff8…d612`, frozen before any call.
* Deviations: `DEVIATIONS.md` (D1–D5).
* Numbers: `results.txt`.
* Hashes of the code, of the states and of the item list: `MANIFEST.sha256`.

## Summary

* **The question.** This is a test of **model capacity**. The decisive fact, the tables the migration touches, is
  diluted in a long, realistic schema. The question is whether the verdict stays non-inferior to the one from the
  native state.
  * Guard 0.1.17 **does not build states like this**: it shows at most 8 tables and lists the others by name only.
  * The result is useful for deciding the served ceiling and for future uses: long sessions in `intent_check`, a whole
    PR and a large schema, if the cut changes.
* **The data.** The 184 migrations of v3 (56 risky and 128 benign), with labels obtained by execution, in regime R. The
  questions and the verdict rule are exactly those of the product (`Q_LOST`, `Q_FAILS`, threshold 0.5).
* **The result.** 16k, 32k and 64k are **non-inferior** to the native state on all four criteria, with all 184 items.
  * At 64k, accuracy is the same (0.880 → 0.880, CI of the drop [−2.2; +2.2] pp), with 2 items worse and 2 better.
  * The AUROCs do not move.
* **120k**: exploratory, with 65 of 184 items. No verdict changed, but it cannot become the ceiling (D3).
* **Pre-registered ceiling: 64k tokens.**
* **What gets worse with length** is the **calibration of `Q_FAILS`**: ECE goes from 0.034 to 0.063 at 64k, and the
  probability crosses 0.5 on 8 items. The verdict hardly changes because `Q_LOST` usually decides together with it.

## Design

* **Items and states.**
  * L0 is the product's state, checked byte by byte against `build_state` 0.1.17.
  * The long lengths fill the schema block with **real tables from other projects** (the largest catalog out of 11
    projects, in the catalog format, with replica statistics).
  * There is no name, FK or enum collision with the item, and no distractor name appears in the migration.
  * The size is measured with the model's tokenizer. The targets are 16k, 32k, 64k and 120k tokens **per sequence**.
    Measured by usage, the median came out at 15.7k, 32.0k, 64.7k and 121.7k.
* **Depth.**
  * At 16k and 32k, the relevant tables sit in the middle.
  * At 64k and 120k they sit at the start, in the middle or at the end, with one depth per item, balanced (62/62/60).
* **Control L0h.** This is the header of the long conditions ("…and other tables of the database") with no distractor
  at all.
* **Questions.** `Q_LOST` and `Q_FAILS`. `Q_HALF` was dropped because it does not go into `FileVerdict.kind` or
  `reason`, and each question is a separate sequence on the server.
* **Run.** Concurrency 2 below 64k and 1 at 64k and 120k. Prefix cache across items was allowed, except in the cold
  requests.
* **Criteria** (per length, paired with L0, n = 184):
  * C1: accuracy drop ≤ 2 pp, with the upper limit of the 95% CI ≤ 4 pp;
  * C2: AUROC drop ≤ 0.02 on each question;
  * C3: recall ≥ L0 − 2 items;
  * C4: false alarm ≤ L0 + 3 items.

  The ceiling is the largest length that passes, with all the smaller ones passing too.

## Result

| | n | Accuracy | Drop [95% CI] | Worse/better | Recall | False alarm | AUROC lost | AUROC fails | ECE fails | Decision |
|---|---|---|---|---|---|---|---|---|---|---|
| L0 | 184 | 0.880 | | | 54/56 | 20/128 | 0.940 | 0.962 | 0.034 | |
| L0h | 184 | 0.880 | 0.0 | 0/0 | 54/56 | 20/128 | 0.932 | 0.961 | 0.043 | control |
| 16k | 184 | 0.875 | +0.5 [−1.1; +2.2] | 2/1 | 53/56 | 20/128 | 0.926 | 0.956 | 0.045 | **passes** |
| 32k | 184 | 0.875 | +0.5 [0.0; +1.6] | 1/0 | 54/56 | 21/128 | 0.932 | 0.957 | 0.049 | **passes** |
| 64k | 184 | 0.880 | 0.0 [−2.2; +2.2] | 2/2 | 54/56 | 20/128 | 0.940 | 0.962 | 0.063 | **passes** |
| 120k | 65 | 0.892 (L0 0.892) | 0.0 | 0/0 | 20/20 | 7/45 | 0.926 (0.927) | 0.995 (0.998) | 0.050 (0.052) | exploratory |

* **McNemar**: p = 1.0 at all lengths.
* **|Δp| against L0**: median ≤ 0.01 at all lengths. Large changes are rare: |Δp| > 0.10 on 6 of 184 items in `Q_LOST`
  and on 11 to 14 of 184 in `Q_FAILS`.
* **Depth at 64k** (descriptive, n ≈ 61):
  * start: 1 item worse and 1 extra alarm;
  * middle: 1 item better;
  * end: the same.

  There is no sign of "lost in the middle".
* **The header alone (L0h)** already takes 0.009 off the AUROC of `Q_LOST`, and this effect does not grow with length.

## Latency

**Cold** (n = 5 per length, unique distractors, no prefix in cache, 2 questions per request):

| | Total time, median (min–max) | Model (Server-Timing), median | Queue, max |
|---|---|---|---|
| L0 | 1.7 s (1.1–2.3) | 1.1 s | 0 |
| 16k | 4.6 s (4.0–5.3) | 3.8 s | 0 |
| 32k | 10.6 s (9.3–12.1) | 9.6 s | 0 |
| 64k | 24.5 s (11.9–29.6) | 17.4 s | 6 s |
| 120k | 43.9 s (31.5–60.5) | 24.2 s | 19 s |

**With cache**, in the paired runs, the median total time was 3.1 s (L0), 8.7 s (16k), 22.8 s (32k, run under load and
at concurrency 2), 24.2 s (64k) and 50.5 s (120k). The server shares its GPU with the production GLM, so these times
include production load.

## Recommendation

* **Served and advertised ceiling: 64k tokens per state.**
  * 120k did not worsen any verdict on 65 items, but it is exploratory. To advertise above 64k, the remaining 119
    items still have to run under a new pre-registration: ~29 M usage, ~14.5 M unique.
  * Latency also weighs: ~25 s cold at 64k and ~45 s at 120k.
* **`MAX_CHARS`: raise from 60,000 to 200,000.**
  * The pre-registered rule gives 205,138: (64,000 − 500) divided by the q99 of 0.310 tokens per character of the real
    states. The round value, 200,000, sits below it.
  * The current comment in `migrations.py` ("the hosted API reads up to 32k tokens") is wrong: **60,000 characters are
    ~15k tokens at the median and ~19k at q99, not 32k**. The product's states have ~4 characters per token.
  * Even without changing the model's ceiling, the current cut is **3.4 times more conservative** than the comment
    itself assumes.

## Caveats

* **This is capacity, not current use.** The guard does not build long schema states. Long migrations (many
  statements), which are the real source of a large state today, **were not tested**.
* **The distractors come from the same 11 projects**, all with 20 seeded rows. A real large schema would be more
  varied. And distractors from a similar domain (another `User`, another `Session`) were excluded for name collision,
  which may make the task easier than in a single large database.
* **The calibration of `Q_FAILS` gets worse** with length (ECE 0.034 → 0.063, Brier 0.050 → 0.064 at 64k). Whoever uses
  the probability, and not only the verdict, should know this.
* **n = 184** with 21 items that fail: an effect of 1 to 2 pp is not ruled out (the CI of the drop at 64k goes up to
  +2.2 pp).
* **Deviations.**
  * D1: 32k ran last, because of a bug in the concurrency lock that refused it with no call at all.
  * D2: the budget began to be counted in unique tokens, and consumption was 61.2 M of usage, ~30.6 M unique.
  * D3: 120k stays exploratory.
  * D5: the secondary with `intent_check` did not run.
