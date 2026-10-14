# Deviations from PREREG.md

1. **Transport (2026-10-13 ~21:10 UTC, after 2,994 of ~18,300 actions, no result looked at).** The study key goes
   through the gateway's internal lane, capped at 600 input tokens/s and 1 request in flight (set on 10 Oct to protect
   the GLM sharing the GPUs); that held the run to ~0.65 actions/s (~7 h). Caio accepted a slower GLM during the study,
   so the remaining actions call the same model server directly through an SSH tunnel (127.0.0.1:8010 on the B200,
   the server behind the gateway: same weights `Ekbasis-27B-INT4`, same serve code, same prompts and questions). The
   gateway adds no transformation to the request or the answer, so scores are unaffected; latency numbers from this
   point measure the model server without the gateway queue, and the latency comparison uses only them.
2. **Workers** raised from 2+1 to 4+2 at ~20:10 UTC (no effect on scores).
3. **Hardware (2026-10-13 ~21:50 UTC; still no result looked at).** Scoring on the B200 halved the production GLM's
   prefill (queue reached 43), so it was paused at 3,460 actions. With Caio's OK, a dedicated RTX PRO 6000 (Vast
   55815301, vLLM 0.31.0 as on the B200, the model repo's own `serve_vllm.sh` + `serve.py`, TP1) scores the study.
   To keep one hardware for every score, **all actions are scored again on the RTX** (`out_rtx/`, analysed with
   `CTRL_OUT=out_rtx`); the 3,460 B200 scores are kept only to report how much scores differ between the two
   machines (same weights, different GPU and tensor parallelism).
