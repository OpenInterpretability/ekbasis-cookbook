# Deviations and notes (PREREG_v6)

1. **Ekbasis restart windows** (12:47–12:52 and 14:22–14:27 UTC, notified by the lead). No v6 request fell in them:
   the PREREG was frozen at 14:45 UTC, and every answer was written after it. 0 errors, so no item was retried.
2. **Question field.** Every request carries the question text in `instructions`, the field the server reads (the
   product's frozen questions, ekbasis.migrations.Q_LOST/Q_FAILS/Q_HALF). Checked in data/requests_v6.jsonl.
