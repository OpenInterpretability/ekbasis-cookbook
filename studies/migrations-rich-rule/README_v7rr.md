# Retest of policy (d) against product 0.1.21 (Rails v7 held-out; P5 dev) — not published

**Status:** finished on 2026-10-11. Zero calls, nothing published, no push.

**Result on Rails v7, the primary (307 answered, 119 risky):**
- **EKB 0.1.21 against R_NOSEED: a tie.** Δ = +0.7 pp, CI [−1.3; +2.6], McNemar 6/4, p = 0.75.
- **No policy is eligible.** All of them go over the 15% false-alarm cap: EKB 17.0%, R_NOSEED and (d) 18.1%, OR 20.2%.
  By the pre-registration, no policy is chosen.
- **Recall:** 119/119 in all arms. The warning of (d) buys nothing (0 extra risky items) and costs 4 warnings on benign
  items.
- **R_RICH** (with the seeding heuristics, not a candidate) gets 0.964 with 5.9% false alarm. It is again a sign that
  what separates the arms here is the synthetic database, not the model.

## Pre-registration and freeze
- `PREREG_v7rr.md` (`1e8e4bd2…`) and `V7RR_FREEZE.sha256` (`30f3a154…`), at 22:26 UTC, before the v7 labels.
- Exposure declared: the aggregates in `ADDENDUM_A1.md`. No per-item label.
- **Adapter `facts_cut.py`** (cut layout):
  - conversion: v7 300/300 and P5 190/190, no item left out;
  - validation without labels with cut 0.1.20 states generated from the raw facts: identical predictions on 190/190
    (v3) and 526/526 (D2), and identical probe facts.
- EKB verdict: `analysis_v7.product` (probes decided in code and a schema-only rule), in a separate process
  (`ekb_v7.py`, `ekb_v7.json`).

## Results (`results_v7rr.txt`)

| Rails v7 (n = 307) | Accuracy | Recall | False alarm | Recall w/ warnings | Eligible? |
|---|---|---|---|---|---|
| (a) EKB 0.1.21 | 0.896 | 1.000 | 0.170 (32/188) | 1.000 | no (false alarm > 15%) |
| (b) R_RICH | 0.964 | 1.000 | 0.059 (11/188) | — | not a candidate |
| (c) R_NOSEED | 0.889 | 1.000 | 0.181 (34/188) | 1.000 | no |
| (d) R_NOSEED + EKB warning | 0.889 | 1.000 | 0.181 | 1.000 (4 warnings on benign) | no |
| (e) R_NOSEED OR EKB | 0.876 | 1.000 | 0.202 | 1.000 | no |

- EKB − R_NOSEED: +0.7 pp [−1.3; +2.6], p = 0.75 → **tie**.
- EKB − R_RICH: −6.8 pp [−9.8; −3.9], p < 0.001.

**P5, dev, sensitivity only** (v3 under 0.1.21, n = 184):
- EKB 0.902 (false alarm 12.5%), R_NOSEED 0.913 (9.4%), Δ = −1.1 pp, tie;
- there (d) is eligible and chosen: accuracy 0.913, recall with warnings 56/56 against 54/56 for EKB, 5 warnings on
  benign items.

## Where they err (Rails v7)
- **Both err together on 28 benign items**, the great majority of the false ones:
  - 26 in openproject: "add_uniqueness_for_*_names" migrations, renames of settings/permissions and cleanups of
    preferences, all data UPDATEs that deduplicate or rename;
  - 2 decided by the product as a schema error.

  In the seeded database, these UPDATEs find no row (no duplicates, no literal value), and the label says ok. In a real
  database, deduplicating names renames existing rows. **This is the same artifact that R_NOSEED was built not to
  exploit.** This is why the 15% cap fails for all of them.
- **Only EKB errs:** 4 alarms, all in consuldemocracy and openproject (`set_*_name_limit`, `confidence_score default`,
  `create_project_types`). These are the 4 warnings of (d).
- **Only R_NOSEED errs:** 6 alarms, among them `change_debates_title_length` (shortened varchar: "may fail"), a unique
  index on `user_preferences`, `fix_uniqueness_on_enumerations` and `add_uniqueness_for_watchers`.

## What this means for the product
- **Against the current product, with cut and probes, the model still ties with the rule on the same facts.** This
  holds on the Rails held-out set (+0.7 pp, CI crosses 0) and on P5. H1 ("the model adds") fails for the fourth time.
- **The policy choice stays open on Rails v7.** No policy respects 15% false alarm, because the synthetic label marks
  as "ok" deduplications and renames that, in production, change data. This weighs equally on all arms. It is not a
  reason to swap (d) for EKB alone:
  - the accuracy difference is +0.7 pp, with no significance;
  - recall is equal (100%);
  - the warning costs only 4 alarms.
- **Recommendation, outside the criterion (the author's reading):** keep (d) as the design, already chosen on the v5/v6
  held-out set and on P5. Measure false alarm with labels from a realistic database (repeated values, duplicate names)
  before fixing a cap, because a 15% cap over synthetic labels is measuring the seeder.
- **Side finding (reported separately):** the p2 items have no dependencies in the catalog, so the "0.1.20" states of p2
  (T2 of P2) came out WITHOUT the schema cut. The measurement of 0.1.20 on p2 did not exercise the cut.

## Files
- `PREREG_v7rr.md`, `V7RR_FREEZE.sha256`;
- `facts_cut.py`, `load_v7.py`, `validate_cut_adapter.py`, `ekb_v7.py`, `ekb_v7.json` and `score_v7.py`;
- `results_v7rr.txt`.
