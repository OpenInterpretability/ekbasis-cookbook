# Held-out on frameworks (v5 Django/Alembic, v6 Rails): rule, model and product policy (not published)

**Status:** finished on 2026-10-11. Zero calls to Ekbasis, nothing published, no push, v7 not opened.

**Result (aggregate, 523 answered migrations, 88 risky):**
- **R_NOSEED against EKB: a tie by the criterion.** Δ = −1.5 pp, CI [−3.1; 0.0], McNemar 5/13, p = 0.096. The rule is
  numerically ahead.
- **R_RICH:** "the rule is better", Δ = −2.5 pp, CI [−4.2; −0.8], p = 0.007.
- **H1 ("the model adds") fails again** in all cuts.
- **Policy chosen by the criterion: (d)**, "R_NOSEED decides; EKB above the threshold becomes a warning".
  - Verdict: accuracy 0.960, false alarm 3.0%.
  - Recall with warnings 0.920, equal to EKB's.
  - Cost: 14 warnings, of which 13 on benign items (3.0%).

## Pre-registration and freeze
- `PREREG_fw.md` (`13576d40…`) and `FW_FREEZE.sha256` (`097d16e9…`), at 21:04 UTC, before any label.
- Deviation D1 (`DEVIATIONS_fw.md`, `FW_FREEZE2.sha256`): a fix to the import order in the scorer, with no labels read
  and no effect on the EKB verdict (0/739 differences).
- Prior exposure declared: the aggregate counts in `PREREG_v5.md`.
- **Adapter `facts_v5.py`:**
  - the 0.1.15 state exists only as text, so the adapter parses it back into the facts structure, with empty probes;
  - it converted 0 failures out of 416 (no item left the arms);
  - validated without labels: v3 192/192 and D2 529/530 predictions identical to those from the raw facts.
- Rules: the same as in study 1 (`rule.py` `f4c21f4d…`, `rule_noseed.py` `285c87c9…`), with no change.

## Results (`results_fw.txt`)

| Aggregate (n = 523) | Accuracy | Recall | False alarm | Recall w/ warnings | Warnings on benign |
|---|---|---|---|---|---|
| (a) EKB | 0.945 | 0.920 (81/88) | 0.051 (22/435) | 0.920 | |
| (b) R_RICH | 0.969 | 0.909 | 0.018 | (not a candidate) | |
| (c) R_NOSEED | 0.960 | 0.909 (80/88) | 0.030 (13/435) | 0.909 | |
| **(d) R_NOSEED + EKB warning** | **0.960** | 0.909 | **0.030** | **0.920 (81/88)** | 13/435 |
| (e) R_NOSEED OR EKB | 0.937 | 0.920 | 0.060 | 0.920 | |

| By framework | EKB | R_NOSEED | Δ, 95% CI | McNemar |
|---|---|---|---|---|
| Django (242) | 0.955 | 0.955 | 0.0 [−2.1; +2.1] | 3/3, p = 1 |
| Alembic (141) | 0.986 | 0.986 | 0.0 [−2.1; +2.1] | 1/1, p = 1 |
| Rails (140) | 0.886 | 0.943 | −5.7 [−10.0; −1.4] | 1/9, p = 0.021 |

Policy choice: (a), (d) and (e) are eligible (false alarm ≤ 15% and recall with warnings ≥ 0.920); (c) is not, because
recall stays at 0.909. Among the eligible ones, (d) has the highest accuracy.

## Where they err
- **EKB:**
  - almost all of its excess of alarms comes from Rails: 15/99 benign, against 7 for the rule;
  - 6 of them are "validate not null" migrations from mastodon, which the model reads as loss;
  - in Django and Alembic, the two tie item by item (3/3 and 1/1 discordant).
- **Both err together** on 7 risky items:
  - 6 in Django: data failures in saleor (`0063` and `0036` `*_order_token`, `0095`, `0023`), a loss in saleor
    (`discount/0013`) and paperless `0010`;
  - 1 numeric precision case in Rails (maybe).

  This is the limit of what the 0.1.15 state shows, without probes.
- **The warning of (d)** catches exactly 1 risky item that the rule lets through (saleor
  `0032_save_payment_order_token`), at the price of 13 warnings on benign items.

## What this means for the product
- **On a clean held-out set, with frameworks and projects that no rule saw, the model adds no accuracy beyond the
  facts:**
  - in Django and Alembic, an exact tie;
  - in Rails, the rule is better;
  - in the aggregate, a tie by the criterion, with the rule ahead.

  This confirms study 1 and the Kubernetes and dbt pilots.
- **Product policy by the pre-registered criterion: (d).** The deterministic verifier (R_NOSEED over the facts
  pipeline) decides what fails the check. Ekbasis becomes a review warning.
  - Gain from the warning: recall 0.909 → 0.920, that is, +1 risky item out of 88.
  - Cost of the warning: 13 false warnings out of 435 benign items.
  - It is worth as a "cheap second opinion", not as the engine of the guard.
- The message that holds: "the guard builds the facts of your database and applies PostgreSQL semantics; a calibrated
  model suggests review in borderline cases". What does not hold: "the model predicts what rules do not predict".

## Limits
- Labels from a seeded database, as in study 1. R_NOSEED avoids the seeder's heuristics, but EKB and the labels are
  still synthetic.
- n = 88 risky in the aggregate. The advantage in recall with warnings is 1 item, so the criterion "≥ EKB" is met at the
  limit.
- The 0.1.15 state had no probes and no schema cut. With 0.1.20, both arms would have more facts, and the 7 risky items
  that both miss are candidates for probes.
