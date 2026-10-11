# Ekbasis vs. a large general LLM as the judge, on migrations

*Pre-registered, run 11 October 2026. Plan: [PREREG.md](PREREG.md) (sha256 in [PREREG.sha256](PREREG.sha256), written
before any call to the LLM judge). Deviations: [DEVIATIONS.md](DEVIATIONS.md).*

## The question

"Why not just ask a big LLM?" On the 184 labelled migrations of the v3 sample, with the exact state the migration guard
0.1.19 builds (schema cut) and the same two questions, does Ekbasis (27B, one forward pass, no generated tokens)
match GLM-5.3-Flash (a large MoE model we serve), used as a judge with its default reasoning?

## Result

| | Ekbasis | GLM-5.3-Flash |
|---|---|---|
| Accuracy, with replica statistics (primary; no answer counted risky, as pre-registered) | 0.897 | **0.918** |
| Accuracy, with replica statistics, on the 152 items the GLM answered | 0.961 | **0.987** (−2.6 pp [−5.3, −0.7]) |
| Accuracy, without replica statistics | **0.886** | 0.880 (+0.5 pp [−3.8, +4.9]) |
| Brier (mean of the two questions), with replica statistics | 0.102 | **0.012** |
| Items the GLM did not answer (reasoning used the 4,000-token cap) | 0% | 17% (with) / 23% (without) |
| Median latency | **2.6 s / 2.0 s** | 22.5 s / 14.3 s |

- C1 (Ekbasis non-inferior by 2 pp) failed with replica statistics and passed without. C2 (Ekbasis Brier ≤ GLM) failed
  in both.
- Reading: with the facts in the state, a large general LLM is at least as accurate and better calibrated on
  migrations. Ekbasis's advantages here are operational: several times faster, always answers, no generated tokens.

## Deviations

D1 lowered the token cap and timeout after a stalled first run; D2 switched to streaming because long calls died at
the tunnel's 100-second limit (infrastructure errors are re-asked, never counted against the GLM); D3 raised
concurrency. All before looking at any metric. See [DEVIATIONS.md](DEVIATIONS.md).

## Files

- `run_glm.py` (the judge runner), `analyze.py` (the registered analysis), `glm.R.jsonl`, `glm.N.jsonl` (answers).
- The states and the Ekbasis answers come from the schema-cut study (`../migrations-schema-cut/`); labels from the v3
  sample (`../migrations/`).

Published copies differ from the sealed ones only by sanitization: the runner reads the LLM endpoint from `GLM_BASE_URL` instead of our host name; the sealed hashes in `PREREG.sha256` are of the originals.
