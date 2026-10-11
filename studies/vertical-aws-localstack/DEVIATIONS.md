# Deviations

None that invalidate a call. Each of the three team-lead notices was checked:

1. **Question field.** The team lead warned that only `instructions` is read, not `question`.
   - `guard.py` builds every question with `ekbasis.prompts.yes_no`, which returns
     `{"type": "noul", "instructions": ...}`. No code uses `question`.
   - The answers show that the server read the questions. The three questions get very different probabilities on
     the same state, for example s6 in dev: lost 0.148, down 0.950, fails 0.978.
   - No call was voided and nothing was re-frozen. `FREEZE.sha256` is unchanged.
2. **vLLM restart windows** (12:47–12:52 and 14:22–14:27 UTC).
   - Every Ekbasis call ran after both windows: dev at 14:55 UTC and test at 14:56–14:57 UTC, according to the file
     times in `answers_*`.
   - There were 0 errors, 0 retries, and no `.err` files.
3. **Labelling changes made before any model call.** These are already declared in PREREG:
   - DynamoDB relabelled after a labeller bug;
   - the replace-gap clause for "down";
   - s28 excluded as a LocalStack gap.
