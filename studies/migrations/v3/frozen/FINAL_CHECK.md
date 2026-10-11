# The merged commit against the evaluated one

The evaluated commit is `b18bb43`. The commit for merge is `e5b606f`, rebased on main with intent_check (PRs #11 and
#12). The code between them changes only text:
- the "cannot foresee" prefix is no longer repeated;
- a migration that needs a superuser gets a "review this one by hand" note;
- the "About" link points at the release tag;
- plus documentation.

Rebuilt with the code at `e5b606f`, the state text is identical to the evaluated requests:
- **v3:** 184 of 184;
- **v2 (A2):** 582 of 582.

The replica statistics block is left out on both sides, and enum lines are compared as a set.

The verdict and reason (`FileVerdict.kind` / risky) recomputed with `e5b606f` from the v3 answers match the evaluated
ones in 184 of 184.

**End to end at `e5b606f`.** The 5 pull requests of the private test repository gave the expected results:
- data loss: risky, 98%;
- failure: risky, 96%, with "nothing in the file would be applied";
- benign: ok;
- typo: risky, "an error in the pull request itself";
- `COPY ... TO PROGRAM`: cannot foresee, not run.

Each pull request has one comment, and the API key does not appear in the logs.
