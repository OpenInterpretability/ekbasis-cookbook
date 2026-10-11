# Deviations and notes (PREREG_v2)

1. **The product changed after the evaluated commit (24957b4).** Final commit `b18bb43` of the PR.
   - **Security.** Migrations run as a throwaway non-superuser role, and the Action's scratch container has no network.
   - **Comment escaping.** Paths and errors from the pull request are escaped in the comment.
   - **Reasons decided in code** ("fails ... nothing applied" before "loses").
   - **Enum types listed in a stable order.**

   None of the questions, thresholds or verdict rules changed. Measured on the 582 items (`verify_final/`):
   - **Superuser against role.** Building the schema both ways and rendering the state with the final code gives the
     same text in 582 of 582. A first comparison found 10 differences, all in trigger.dev, all from enum types listed
     in an arbitrary order (fixed in the final commit), none from privileges.
   - **Final against evaluated.** The final state text equals the evaluated A2 text in 582 of 582. The comparison
     leaves out the "Rows:" statistics, which come from the replica, and compares enum lines as a set.
   - So the product that ships reads the same state as the one evaluated. Two things differ: the order of enum lines
     (arbitrary before) and the reason text printed (not part of the state).
2. **H7 was rerun at the final commit** (see the H7 entry of the report).
