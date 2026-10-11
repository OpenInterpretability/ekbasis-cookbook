# Deviations from PREREG.md

1. **Runner (before the pilot).** `run_ekbasis.py` was changed to send the same request body with `urllib` instead of
   the client, so it could record the `Server-Timing` header (gateway queue and model time, separately). Request body,
   endpoint, questions and retries (3) are unchanged. Hash in `PREREG_sha256.txt`.
2. **Analysis code (during the run, before any result).** `analysis.py` gained the registered secondary analyses that
   were not yet coded: stratum-A rule rows, the per-statement aggregate, the ">2% missing" rule and the model against
   the transactional labels. No threshold or population changed.
3. **H5 was computed on the wrong population in the first report.** PREREG §5.3 registers H5 (ECE ≤ 0.10) on stratum A.
   `analysis.py` computed it on all 582 items (0.093, "PASS"). The registered value is 0.142: **H5 fails**.
   `recompute.py` uses stratum A. H1-H3 were computed as registered.
4. **Tokens.** The server reports about 3× the estimated tokens: it counts the state once per question. Total
   4,389,789 input tokens for 582 requests.
5. **Reproducibility of the synthetic rows.** The seeder walks tables in an order that depends on PostgreSQL object
   ids, so an independent rebuild draws different synthetic values: 183 of 582 states differ, and 2 of 582 items get a
   different `lost` label. The frozen code was not changed. The released labels are those of the run that was scored.
6. **GLM baseline.** Planned with the default model name `glm-5.2`; the operator asked for `glm-5.3-flash` (set with
   `GLM_MODEL`, no code change). The first address given for the endpoint was an old hostname that no longer served
   (HTTP 530); the run used the current production address. No request reached the old one, so no answer changed.
