# Pre-registration: Ekbasis vs. a large general LLM as the judge, on the same migration states

Written 2026-10-11, before any call to the LLM judge in this study.

## Question
"Why not just ask a big LLM?" On the same 184 labelled migrations (the v3 sample; labels by execution on seeded
databases), with the exact state the migration guard 0.1.19 builds (schema cut), does Ekbasis (27B decision model,
one forward pass, no generated tokens) match a large general LLM used as a judge?

## Arms
- **EKB**: Ekbasis answers already recorded in the schema-cut study (`corte_schema/data/ans_t2.jsonl`, arm `new`),
  frozen before this study. Same states, same questions.
- **GLM**: GLM-5.3-Flash (MoE, served by us), default reasoning effort, temperature 0. Prompt = the identical state
  text + the identical two questions (the `instructions` of Q_LOST and Q_FAILS), asking for a JSON object
  `{"lost": p, "fails": p}` with probabilities in [0, 1]. One retry if the JSON does not parse; still unparsable →
  "cannot foresee" (counted risky, fail closed, as the product does).
- Verdict for both arms: the product's code (`fails` if p_fails ≥ 0.5, else `loses` if p_lost ≥ 0.5; decided-in-code
  items keep their decision; schema_error_autocommit forces fails).

## Regimes
R (replica statistics, primary) and N (no replica). R runs first.

## Metrics
Accuracy (risky vs ok), recall on risky, false alarms on benign, reason exact, AUROC and Brier per question, median
latency, input and output tokens per item.

## Criteria (decided now)
- C1 (non-inferiority): EKB accuracy ≥ GLM accuracy − 2 pp (point estimate), with the paired bootstrap 95% CI reported.
- C2: EKB Brier (mean over both questions) ≤ GLM Brier.
- Reported without a target: latency ratio and token ratio.
Outcome wording: if C1 passes, "Ekbasis matches a large LLM judge"; if EKB accuracy is ≥ +2 pp above GLM with a CI
above 0, "beats"; if C1 fails, "a large LLM judge is more accurate", stated plainly.

## Operational
Concurrency 2 on the GLM (production service; it must keep serving). No changes to the server.
