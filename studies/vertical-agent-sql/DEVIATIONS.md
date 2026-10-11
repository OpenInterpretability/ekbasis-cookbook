# Deviations

1. **Session interrupted (11 Oct 2026, ~15:30–17:50 UTC).** The agent stopped on a session limit after labeling and
   before writing the pre-registration hash. The lead's resume message said the pre-registration was already frozen;
   it was not: no hash had been sent and **no Ekbasis request had been made** (no `answers_*.jsonl` existed). The
   pre-registration was finished, hashed and sent after the restart, before the first request.
2. **Question field.** The lead warned that the question text must go in `instructions`, not `question`. This study
   builds its questions with `ekbasis.prompts.yes_no`, which uses `instructions`, checked before the first request. No
   call was affected.
3. **Restart windows** announced by the lead (12:47–12:52 and 14:22–14:27 UTC) fell before any request of this study.
4. **Report columns (after the test run, no effect on any metric).** `analyze.py` printed per-row probabilities under the
   same keys as the labels, so the printed `lock` column showed p_lock instead of the label. The metrics were computed
   from the right fields; the row listing now uses `p_beyond`, `p_fail`, `p_lock`. analyze.py's hash changed for this
   only; `analysis_test.txt` was regenerated (same numbers).
5. **A defect of the state text, found when reading the test false alarms.** `MODES["c"]` says psql -c runs all
   statements "as one transaction". For a single statement there is no transaction block, and CREATE INDEX
   CONCURRENTLY runs fine (E09); the text led the model to p_fail 0.974. Not fixed (the test is run once); reported.
6. **Exploratory analysis** (`exploratory.py`, written after seeing the test answers): Ekbasis with only beyond+fail, and
   a code rule for locks. Not pre-registered; reported as hypotheses for the next study.
7. Labeling: the seed's events table was cut from 6M to 1.5M rows and B19's SQL was changed (its first version, a
   cartesian DELETE ... USING, ran past the 25 s stop and would have been labeled benign) before labeling finished and
   before the pre-registration was hashed (the events cut is in PREREG.md; the B19 change only here).
