# Deviations

- D1 (2026-10-11 ~20:05 UTC, after 2 of 184 R answers and before looking at any metric): the first run stalled —
  in 14 minutes only 2 answers came back (median 26 s and ~930 reasoning tokens, one call apparently reasoning toward
  the 12,000-token cap). Changed: max_tokens 12,000 → 4,000, request timeout 900 → 300 s, concurrency 2 → 4 (the GLM
  had headroom: 24 running, ~2,000 tok/s), answers written as they complete instead of in order. A call that hits the
  cap without a JSON answer is retried once and then counted as "cannot foresee" (risky), as pre-registered. The 2
  answers already written are kept.
- D2 (~20:20 UTC, after 24 R answers, before looking at any metric): long calls died with HTTP 524 (the tunnel's
  100-second limit), which is infrastructure, not the model. Changed: requests are streamed (the connection stays
  alive while the model reasons); an infrastructure error (HTTP error, timeout, dropped stream) is recorded as
  `infra_error` and the item is asked again on the next pass, never counted against the GLM. Only a completed answer
  with no parsable JSON (after one retry) counts as "cannot foresee". Analysis uses the last completed record per id.
- D3 (~20:30 UTC, still before any metric): with ~45 production requests on the GLM, one judge call takes ~270 s
  (~1,900 reasoning tokens at ~7 tok/s); at concurrency 4 the study would take ~7 h. Concurrency 4 → 10 (the owner
  allowed free use of the GLM as long as it keeps serving). Nothing else changes.
