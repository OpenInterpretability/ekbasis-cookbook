# Per-client calibration in Ekbasis: a threshold tuned with each repository's feedback

*Pre-registered study, run on 2026-10-11. No new API calls: the study reuses the probabilities already recorded in the
migration studies (v1, v3, v5) and in TS-Bench. The labels come from those studies: real execution of the migrations on
a seeded PostgreSQL, or the labels from the benchmark authors.*

## Summary

- **The question.** Does tuning the threshold (or recalibrating the probability) **per repository**, using the first k
  feedbacks from that client, decide better than the fixed global threshold of 0.5?
- **The clients.** 30 simulated clients in the primary design, each one made of a group and a question:
  - 12 migration repositories (v1) × {lost, fails};
  - 6 TS-Bench suites;
  - in the background, v3 (184 new migrations, 14 clients) and v5 (Django/Alembic, 10 clients).
  - Dev and test were split by hash **before** looking at any label. Dev has 4 repositories and 2 suites; test has 8
    repositories and 4 suites.
- **Result: it did not pass.** On test, with k = 20:
  - **Decision (method A, threshold only):** Δaccuracy +0.018 [−0.006, +0.048]; the CI crosses zero. **H1 fails.**
  - **Calibration (B0, intercept with a prior):** ΔBrier +0.007 [−0.035, +0.068]; at the point estimate, it gets
    worse. **H2 fails.**
  - **Safeguard.** An adversary that marks 20% of the real alerts as "false_alarm" pushes method A down by −0.064
    [−0.120, −0.006] of accuracy, and recall falls from 0.552 to 0.471. **S fails.**
- **Where the existing gain comes from.** From 2 or 3 clients where the global threshold is clearly wrong:
  - lost in mattermost, with 25% false alarm under G (+0.25 accuracy with its own threshold);
  - fails in lemmy, which has no positives at all (+0.12).
  - In the other clients the gain is zero or negative. Most are already at the ceiling: AgentDojo 0.99–1.00; lost in
    kratos 1.00.
- **Where the loss comes from: temporal drift.** In triggerdev, the first 20 feedbacks had almost no migrations that
  lose data. The B0 recalibrator learned "this repository almost never loses data" and started leaving the following
  positives without an alert: −0.45 accuracy at k = 20 and −0.80 at k = 50.
  - A repository's base rate **changes over time**. The hypothesis "each repository has its own base rate" is true on
    average and false at the moment it matters.
- **At how many feedbacks does the gain appear?** At no k ≤ 50 was the CI of A's Δaccuracy above zero on test
  (k = 50: +0.041 [−0.000, +0.110], with only 10 clients).
  - For the product: **if there is a gain, it needs more than 50 labeled feedbacks per repository and per question**.
  - This cannot be tested here: no repository has more than 60 items.
- **Recommendation: do not build automatic per-client calibration.** The manual threshold already exists
  (`--lost-threshold`, `--fail-threshold`). What is worth doing is to show the repository owner their false-alarm rate,
  without changing the threshold on its own (§6).

## 1. Design

**Hypothesis.** Ekbasis returns probabilities, and the products decide with fixed thresholds. A repository may have its
own base rate and style, so a threshold learned from that repository's feedback would decide better. **Generic**
recalibration by domain already failed (TS-Bench, R1); here the test is **per client**.

**Clients** (one client = one group × one question):

| Family | Source | Clients | Feedback order | Role |
|---|---|---|---|---|
| M1 | v1 migrations, 582 items | 12 repositories × {lost, fails} | temporal (the id orders by date) | dev 4 repositories, test 8 |
| TS | TS-Bench, 7,182 steps | agentharm, asb, agentdojo/{workspace, travel, slack, banking} | random, by trajectory, 20 seeds | dev 2, test 4 |
| M3 | v3 migrations, 184 items, product label | test repositories only | temporal | secondary |
| M5 | Django/Alembic v5, 278 answered items | 5 projects | random, 20 seeds | secondary |

**Excluded:** `real_cases/` (63 incidents, at most 8 per repository and almost all positive: they do not form clients).

**Split.** Dev and test come from `sha256("ekbasis-percliente-2026-10-11:" + name)`.
- Dev: hoppscotch, formbricks, langfuse, vaultwarden, agentdojo/banking, agentharm.
- Dev only chose the hyperparameters and the primary method. Test ran once, after the hash of `selection.json`.

**Protocol.** For each k ∈ {5, 10, 20, 50}: the first k feedbacks train and the rest of the client evaluates. At
least 10 evaluation items are required. In TS-Bench, the draws take whole trajectories, so that steps from the same
trajectory do not land in both training and evaluation.

**Methods** (in logit; the decision is score ≥ 0.5):

| Method | What it fits with the k feedbacks |
|---|---|
| G | nothing: p ≥ 0.5 (the product today) |
| A | the threshold that maximizes accuracy on training (on a tie, the one closest to 0.5) |
| AR | like A, with a floor: recall on training does not fall below that of G; with no positive, the threshold does not go up |
| C | A's threshold shrunk toward 0.5: weight k/(k+k0), k0 = 10 chosen on dev |
| B0 | intercept only, q = σ(logit p + b), b ~ N(0, 2²) (the "base rate" hypothesis) |
| B | Platt, q = σ(a·logit p + b), with a prior centered at a = 1, b = 0, s = 2 |

**Metrics and intervals.** For each client: realized accuracy, recall and false alarm, Brier and ECE. Δ is always
method − G. The mean is macro: each client-question weighs the same. The 95% CI comes from a bootstrap over
**repositories** (the two questions of a repository go out together), with 10,000 resamples.

**Feedback noise** (only on the k training feedbacks):
- *flip*: 20% of the labels flipped at random;
- *silence*: up to 20% of the labels, chosen among the positives, become 0. This is the adversary that marks real
  alerts as "false_alarm".

## 2. Pre-registered results (primary test, k = 20, 18 client-questions)

| Hypothesis | Method | Result | Criterion | Verdict |
|---|---|---|---|---|
| H1 decision | A | Δacc **+0.018** [−0.006, +0.048]; recall 0.701 against 0.552 | lower CI > 0 and recall ≥ G − 0.05 | **failed** |
| H2 calibration | B0 (s = 2) | ΔBrier **+0.007** [−0.035, +0.068] | upper CI < 0 | **failed** |
| S decision, flip | A | Δacc −0.008 [−0.038, +0.025] | ≥ −0.01 and recall ≥ G − 0.05 | ok |
| S decision, silence | A | Δacc **−0.064** [−0.120, −0.006]; recall 0.471 against 0.552 | same | **failed** |
| S calibration, flip | B0 | Δacc −0.044; ΔBrier +0.046 | same, and ΔBrier ≤ 0 | **failed** |
| S calibration, silence | B0 | Δacc −0.084; ΔBrier +0.065 | same | **failed** |

**Nothing goes to the product** under the registered criterion.

## 3. Curve by k (primary test, no noise; Δaccuracy [95% CI])

| k | clients | A | AR | C (k0 = 10) | B0 | B |
|---|---|---|---|---|---|---|
| 5 | 20 | +0.009 [−0.003, +0.026] | +0.009 [−0.001, +0.026] | +0.001 [0.000, +0.002] | +0.011 [−0.001, +0.029] | 0.000 |
| 10 | 20 | +0.011 [−0.004, +0.028] | +0.001 [−0.015, +0.021] | +0.003 [0.000, +0.006] | **+0.013 [+0.003, +0.023]** | +0.018 [−0.000, +0.042] |
| 20 | 18 | +0.018 [−0.006, +0.048] | +0.010 [−0.008, +0.040] | +0.000 [−0.009, +0.009] | −0.009 [−0.071, +0.039] | −0.001 [−0.005, +0.004] |
| 50 | 10 | +0.041 [−0.000, +0.110] | +0.041 [−0.000, +0.110] | **+0.032 [+0.002, +0.063]** | −0.039 [−0.190, +0.082] | **+0.011 [+0.000, +0.028]** |

At every k, pooled recall goes up and the false alarm **also goes up**: from 0.028 to 0.15 with A at k = 20. The learned
threshold goes down, because ASB, with low recall at 0.5, dominates the pooled count. In the migrations, the effect goes
both ways.

The two bold cells that sit above zero were not pre-registered as a criterion and do not survive multiple comparisons
(20 cells). B0 at k = 10 turns negative at k = 20 because of triggerdev (§4).

**Secondary.**
- **M3** (k = 10, 8 clients): B0 +0.040 [+0.011, +0.073] and ΔBrier −0.051. It is the only consistent positive signal,
  but it is on 8 clients of 16 to 28 items. With B, recall falls from 0.885 to 0.615.
- **M5:** everything within ±0.005, because the model is already at the ceiling (recall 0.87–0.89, false alarm 2–3%).
  Under silence, A drops recall to 0.37 (k = 20) and 0.18 (k = 50). AR holds at 0.88: **the recall floor works as a
  safeguard**, but brings no gain.

## 4. Why it fails (exploratory, per client, k = 20)

- **Concentrated gain.**
  - Lost in mattermost: prevalence of 3% and 25% false alarm under G; +0.25 with A.
  - Fails in lemmy: no positives; +0.12.
  - Fails in calcom: −0.05 (recall falls from 0.80 to 0.40).
  - The other 15 clients stay between −0.03 and +0.03, and 9 of them exactly at 0.
- **Ceiling.** AgentDojo (0.987–1.000), lost in kratos (1.000) and v5 have no room to improve.
- **Temporal drift.** Lost in triggerdev: the first 20 feedbacks had almost no positives; the evaluation has 45%. B0
  learned a very negative b and missed most of the positives: −0.45 at k = 20 and −0.80 at k = 50.
  - Temporal order is the realistic case: today's feedback decides tomorrow's migrations.
  - Repositories change phase (early on, new tables; later, destructive refactors), and a threshold learned at the
    start turns out wrong.
- **The per-repository base rate is already in the text.** Loss prevalence varies from 3% to 55% across repositories,
  but the model conditions on the content of each migration (AUROC 0.95). The base-rate difference is already explained
  item by item, and a global shift per repository only helps where the model errs systematically (mattermost).

## 5. Limitations

- The clients are simulated with data from studies, not with real feedback. Real feedback is noisier and sparser, and
  it arrives at the verdict level ("correct"/"wrong"), not as a label per question (see §6).
- There are few units: 12 on test, and at k = 50 only 10 client-questions. The CIs are wide. The study does not rule
  out a small gain; it rules out a gain large enough to show up with ≤ 50 feedbacks and to be worth the risk.
- The hyperparameters came from a small dev set (6 clients at k = 20). A stronger prior would reduce the loss on
  triggerdev, but on dev the stronger priors also gained less (C30 +0.016, C100 +0.003).

## 6. Recommendation for the product

**Do not build automatic threshold tuning or per-client recalibration.** It does not gain in any demonstrable way with
≤ 50 feedbacks and it can be poisoned: 20% of false "false_alarm" feedbacks bring recall down. Temporal drift makes the
tuning wrong exactly when the repository changes phase.

What per-repository feedback can safely do:

1. **Diagnosis, not tuning.** With N ≥ 20 feedbacks from a repository, the PR comment or
   `ekbasis feedback --stats` shows "in this repository: X false alarms in N feedbacks". When the rate goes above 20%,
   it suggests `--lost-threshold`.
   - The decision to raise the threshold stays with the owner, who knows the repository's phase.
   - This is the mattermost case: the real gain exists, but it is rare and visible.
2. **If automatic tuning ever exists, only with AR:**
   - a recall floor, so that the threshold never goes up beyond what the positive feedback supports;
   - only with feedback from the key owner (the gateway already checks this, `fb:rid:<rid>`);
   - a maximum change per window;
   - re-evaluation with a sliding window, because of drift.
   - Under silence, AR stayed neutral in all families. Even so it did not gain, so it does not justify the complexity.
3. **Data prerequisite, if one wants to reopen the question with real feedback.** Today the gateway records
   `{verdict, rid, uid, path}`, with no probability, no repository and no question (lost or fails) that the "wrong"
   refers to. Calibrating would need those three fields. This is a schema change on the site, which I did not make.

**Nothing was implemented in the client**, because the criterion did not pass.

## 7. Reproduce

```
cd calibracao
python3 analysis.py dev    # dev_output.txt, selection.json
python3 analysis.py test   # test_output.txt, test_results.json, test_per_client.json
```

You need the cookbook in `studies/` of this repository (or `EKBASIS_COOKBOOK_STUDIES`), the scratchpad's `fw_eval5/`
and the 9 TS-Bench files in `tsbench_raw/`: commit `46358fa`, concatenated SHA-256 `e67381ea…3fed7`, equal to the one
in the study.

| File | SHA-256 | Registered (UTC) |
|---|---|---|
| PREREG.md | `1b46a58c0ee1471110556aedcaa4e28563a3e2769f693b34e2e85135e073bb8b` | 2026-10-11T12:34:57Z, before any analysis with labels |
| analysis.py | `912c16daad5e7103219de43cf5874f3a5928063c18c43a9f20eed77462ff0a14` | same |
| selection.json | `dd90126537df2097e6ce037441fa53919fc4042bb4ee20362aaa851da9ddf49c` | 2026-10-11T12:35:43Z, before the test phase |

Deviations: `DEVIATIONS.md`. There was an A/AR tie on dev; the verdict does not depend on it.
