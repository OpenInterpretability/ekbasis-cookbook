# Deviations from PREREG.md (TS-Bench run)

1. **Parallelism 4 -> 1 at 17:55 UTC (2026-10-10), to protect production.** The full run started at 16:39 UTC with
   4 workers (Addendum 2). From about 16:45 UTC the production GLM on the same B200 fell from ~25-110 to ~3-9 tok/s
   per request. The team lead paused the run (SIGSTOP) at about 17:55 UTC with 4,956 of 7,182 items written, 0 errors,
   then killed it (file intact: 4,956 lines, none broken). The rest runs with `run.py --full --workers 1` on the same
   file; resume skips written ids, and items in flight at the kill had not been written, so they ran again. State,
   questions, decision rule, metrics and hypotheses unchanged. Latencies mix the two regimes.

2. **34 rows removed: an operator launch without the API environment, not a model or API failure.** A relaunch by
   the team lead at 18:01 UTC ran without `EKBASIS_URL`/`EKBASIS_API_KEY`, so the client fell back to
   `http://127.0.0.1:8000` and wrote 34 rows with "Connection refused" (ASB-OPI); no request reached Ekbasis. That
   process was killed at ~18:05 UTC and the 34 rows were removed (4,990 -> 4,956 lines). Backups of the file as it was:
   `FULL_answers.with_localhost_errors.bak.jsonl` (ours) and `FULL_answers.before_cleanup_1806.jsonl` (the lead's).
   Those items then ran normally, with the registered single retry.

3. **Relaunch bookkeeping.** A correct relaunch (hosted URL and key, 1 worker) at 18:07 UTC wrote 20 good rows
   (4,976 lines, 0 errors) and then stopped (its process ended; the lead also killed a run.py process at ~18:07). The
   run was relaunched at 18:08 UTC (venv, hosted URL and key, 1 worker) and is the only writer from then on. At 18:08:55
   UTC: 5,011 lines, 0 errors, 0 duplicate ids.

4. **Second pause at ~18:30 UTC (SIGSTOP on PID 61799, by the team lead).** Even at 1 worker, together with another
   pilot, production GLM fell to ~7 tok/s per request with a queue of 14. The lead is adding a global limit on the
   gateway (1 request at a time + a pause proportional to tokens) and will resume the same process with SIGCONT.
   From then on the run is slower by design. Lines written at the pause check:     6093. An item in flight may time out on
   resume; the registered single retry covers it, and any remaining failure is reported as a failure.
   Resumed by SIGCONT at 18:33:14 UTC. The gateway limiter holds a request at most 20 s and then answers 429; a 429
   that survives the single retry is recorded and reported as a failure.

5. **Run end and analyses.** The run finished with 7,182 rows, 0 failures (no 429 or timeout survived the retry),
   14,012,596 input tokens. The registered analysis (`recompute.py` -> `RESULTS_original.txt`, `RESULTS.json`) and the
   Addendum 3 analysis (`recal_eval.py` -> `RESULTS_recal.txt`, `RECAL_RESULTS.json`) ran unchanged. The per-suite
   table and the leakage checks (`leak_check.py`, `leak_check_thought.py`) were requested after the run and are
   exploratory, not pre-registered.
