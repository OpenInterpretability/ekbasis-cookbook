# Migration guard: code probes, edited migrations, setup SQL (shipped in 0.1.20)

*Pre-registered, run 11 October 2026. Plan: [PREREG_p2.md](PREREG_p2.md) (sha256 in [PREREG_p2.sha256](PREREG_p2.sha256));
addenda 1–5 and deviations in [DEVIATIONS_p2.md](DEVIATIONS_p2.md). Plan and deviations are in Portuguese.*

## What changed in the product

- **Code probes**: on a copy of the scratch database the guard tries three mechanisms seen in real incidents: an INSERT
  whose keys collide with rows already there, an INSERT…SELECT that leaves a NOT NULL column empty, and a DELETE or
  UPDATE of rows a foreign key still references. "Fails" is decided in code only when PostgreSQL reproduces the error
  with real rows; a probe that needs an invented row reaches the model as a conditional fact.
- **Edited migrations** get a verdict on the base schema before them.
- **`--setup-sql`**: SQL run by the scratch admin before the base's migrations, read from the base ref only (tested
  end to end on supabase/auth).

## Result

| | before (0.1.19) | after | criterion |
|---|---|---|---|
| T2 false alarms, 184 v3 migrations, with replica statistics | 20/128 | 20/128 | ≤ 23: pass |
| T2 false alarms, without | 19/128 | 19/128 | ≤ before + 3: pass |
| T2 recall, with | 54/56 | 54/56 | ≥ before − 2: pass |
| T1 new incidents caught for the right reason | 0/4 | 0/4 | underpowered (n = 4 < 10) |

- The probes changed the state of 5 items (2 decided in code, both truly failing) with replica statistics and 3
  without; no verdict changed. **No regression**, and **the gain on new incidents was not demonstrated**: mining 11
  new repositories found only 4 incidents, none of the probes' formats.
- In development (incidents already seen), two that the guard used to miss were caught for the right reason: a
  DELETE of referenced rows (P(fails) 0.13 → 0.92) and an INSERT leaving NOT NULL empty (0.25 → 0.97). They show the
  mechanism; they are not evidence.
- A later check found that the T2 states here were built without the schema cut (the item catalog lacked dependency
  data, so the cut fell back to the previous layout). The cut together with the probes was measured in the Rails v7
  study's P5 on the same 184 migrations (accuracy 0.897, as with the cut alone).

## Files

`PREREG_p2.md`, addenda in `DEVIATIONS_p2.md`, `MANIFEST_p2*.sha256`, `results_p2.txt`, `incidents_p2.jsonl` and
`curation_p2.json` (the new incidents and the excluded commits with reasons), `mined_p2.json` (commit metadata), and the
scripts (`mine_p2.py`, `build_p2.py`, `states_p2.py`, `run_t1.py`, `score_v4.py`, `e2e_auth.py`). States with
third-party SQL are not included; their hashes are in the manifests.
