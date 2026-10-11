# Deviations

None.
- Question field: guard.QUESTIONS is built with ekbasis.prompts.yes_no, which produces
  {"type": "noul", "instructions": ...}. The `question` field was never used, so no call is invalid. The answers
  also differ by question within the same state (for example s8: lost 0.98, down 0.71, exposed 0.001, fails 0.002).
- Ekbasis restart windows (12:47-12:52 and 14:22-14:27 UTC): every call was made between 14:43 and 14:46 UTC
  (dev 14:43-14:44, test 14:44-14:46), outside both windows, with 0 errors. Nothing to redo.
