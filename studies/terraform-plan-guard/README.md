# Terraform plan guard — pilot (parked)

**Status:** parked on 2026-10-11. No product and no v2 for now. Real use is with cloud providers (RDS, buckets, IAM),
which we cannot label without accounts, and the local result did not clear the pre-registered margin.

**Result:** a pre-registered **tie** with a simple rule. Composite F1 was 0.871 for Ekbasis against 0.824 for the rule
(+0.047). The margin needed to "beat" the rule was +0.05.

## Question
Can Ekbasis predict what a `tofu apply` will do better than a fixed rule? It gets a state built only from facts (the
plan JSON plus read-only live facts) and gets specific typed questions. The verdict is decided in code. The three
outcomes are data loss, service interruption and wider exposure.

## Data
- 70 change scenarios, all **written by us** (`scenarios.py`). The providers are kreuzwerker/docker (nginx, postgres
  and redis containers), cyrilgdn/postgresql on a local server, and local, random and null. No cloud account was used.
- Each label comes from **execution**, with no model involved (`runner.py`):
  1. apply v1;
  2. seed data;
  3. plan v2 and read the live facts;
  4. apply the saved plan while probing the endpoints every 0.2 s;
  5. search everywhere for the seeded data and re-run the exposure probes.
- The exposure probes were a login with no password, an outsider role that has only PUBLIC rights, and a port bound
  on all interfaces.
- 69 scenarios were labelled. One was excluded: s56, where our v1 granted on a table that did not exist yet.
- Positives:

  | Label | Positives |
  |---|---|
  | lost | 20 |
  | down | 38 |
  | exposed | 5 |
  | apply failed | 9 |
  | controls (all three false) | 24 |

## Design
- **State** (`tfguard.py`, `facts.py`): uses the world layout. It holds:
  - the current state, from the plan's prior_state plus Docker inspect, volume sizes, whether ports answer, and the
    pg catalog (exact row counts, ACLs, open sessions, columns typed by an extension);
  - a comparison between each file on disk and the content in the state;
  - the actions: actions, action_reason, replace_paths, changed attributes, with secrets redacted;
  - one-sentence provider notes, added only when the change type needs them.
- **Questions:** four yes/no questions (lost, down, exposed, fails) in one request per scenario, at concurrency 1.
- **Decision in code:** risky if p ≥ 0.5 for lost, down or exposed.
- **Rule baseline** (frozen in `tfguard.rule`):
  - delete or replace of a stateful resource;
  - delete or destroy-first replace of a serving resource;
  - a new 0.0.0.0 port, `trust` auth, or a grant to PUBLIC.

## Pre-registration
- `PREREG.md` sha256 is `61b23c0577e703cbe01b7a9079cb6f72b5fe2f60db1dd8ad562b61d95229e85c`. `PREREG.sha256` holds the
  hashes of all code and labels.
- It was sealed on 2026-10-11 at 12:11 UTC, before any model call. The labels were frozen before it.
- Disclosure: we wrote the provider notes after seeing 4 trial labels.
- The pilot had 5 items and checked plumbing only, with no changes after it. The full run had 69 items and 0 errors.

## Results (`answers_full/metrics.json`)

| | Ekbasis F1 | Rule F1 | Ekbasis AUROC |
|---|---|---|---|
| risky (composite, H1) | 0.871 | 0.824 | 0.926 |
| lost | 0.645 | 0.696 | 0.853 |
| down | 0.868 | 0.899 | 0.951 |
| exposed | 0.889 | 0.909 | 0.997 |

- **H1, tie.** The difference is +0.047, under the +0.05 margin. McNemar: 10 items only Ekbasis got right, 6 only the
  rule got right, p = 0.45.
- **H2, pass.** AUROC is at least 0.80 on every label. On F1 per label, though, the rule is ahead on all three. For
  lost, Ekbasis has precision 0.91 and recall 0.50.
- **H4, pass.** On the 24 controls, Ekbasis raises 3 false alarms (12.5%). The rule raises 5.
- **Complementarity** (H3 was pre-registered and passed). On the 22 (item, label) cells where the rule is wrong,
  Ekbasis is right on 18 (82%). Whether that would make "rule + Ekbasis" a useful second layer is **exploratory**: we
  never tested the combined guard. Examples of cells it got right:
  - a named volume that survives;
  - a schema drop that fails because drop_cascade = false;
  - `trust` added on a data directory that is already initialized;
  - an extension drop with CASCADE that deletes a column;
  - interruptions from a role rename, a password change, allow_connections = false, or a schema rename.

## Failure modes
1. **Our note was wrong, not the model.** The note said PostgreSQL refuses to drop a database while sessions are
   open. That is true for RENAME, but for DROP the provider terminates the connections and the drop succeeds. The
   model followed the note: it predicted the apply would fail (p ≈ 0.98) on s42, s45, s47 and s48, and set loss and
   interruption near zero. That accounts for 6 of its label errors. A corrected note was not run.
2. **local_file rewritten after the app appended to it** (s66, s67, s70). The fact was in the state ("51 lines on
   disk, OpenTofu wrote 1"), but the model did not conclude that the data would be lost. The rule misses these too.
3. **Volume mounted at the parent of PGDATA** (s23). The model missed it. The rule caught it only because it is coarse.
4. **Redis with no snapshot** (s34, s35). The provider removes the container by force, so Redis never writes its
   snapshot, and the data is lost even with a named volume or a bind mount. The state had no fact about persistence:
   this is a gap in the state builder.
5. **create_before_destroy with a name or port conflict** (s2, s16, s32). The model predicted an interruption, but the
   apply fails before it touches the service.

## Limits
- n is small.
- We wrote the scenarios, the notes and the rule ourselves.
- Only local providers were covered; real cloud use (RDS, S3, IAM) was not tested.

## Files
| File | What it is |
|---|---|
| `scenarios.py` | the 70 scenarios (sanitized, see below) |
| `runner.py` | labelling by execution |
| `facts.py` | the live facts |
| `tfguard.py` | the state builder, questions, decision and rule |
| `ask.py` | the Ekbasis calls (reads the study key from a local file; the key is not here) |
| `evaluate.py` | the evaluation: `python3 evaluate.py answers_full` rewrites `answers_full/metrics.json` |
| `evaluate_output.txt` | its output, including the per-item table |
| `labels.json`, `labels_excluded.json` | the labels |
| `PREREG.md`, `PREREG.sha256` | the pre-registration and the hash log |
| `answers_full/` | per scenario: P(yes) per question, verdict, rule output, request id, usage and the exact state sent; `metrics.json` |
| `runs/s*/` | per scenario: `main.tf` (v2), `plan.json`, `facts.json` and the execution result `result.json` |

**Recompute.** `python3 evaluate.py answers_full` on the published files gives a `metrics.json` equal to the one
from the run (checked on 2026-10-11).

**What was left out.** The run logs (`label_run.log`, `ask_full.log`), the 5-item pilot answers, the smoke test, the
binary plans (`plan.bin`), the Terraform state files, the lock files, the bind-mount and ledger directories written
by the scenarios, the provider plugin cache and the virtualenv. None of them is needed to recompute the results.

**Sanitization.** The published copy differs from the one that ran only in local paths:
- `scenarios.py` spelled out the Docker socket under one user's home directory. It now builds the same path with
  `os.path.expanduser("~/.docker/run/docker.sock")`. So its hash no longer matches `PREREG.sha256`: the sealed
  file had sha256 `c96d57bb1be6c8e23be90d397d28bcebe4aa46e3fa79afdead915fbd78f2ef30`; this copy has
  `4f690bad91732e29b085030211a705d1aef092348d9111763a12658010bce8b8`. The sealed original is kept outside this repo.
  Every other file in `PREREG.sha256` is published unchanged and matches its hash.
- In `runs/` and in four states in `answers_full/` (s35, s66, s67, s70), the absolute path of the study's working
  directory was replaced by `$STUDY_DIR`, and the Docker socket path by `$HOME/.docker/run/docker.sock`. In those
  four states the model saw the absolute path; the probabilities are the ones it returned for that text.
- The passwords in the scenarios (`tfgpass`, `apppass`, `apppw`, `readerpw`, `outsider`, `newpw`) are fixtures of
  throwaway local containers bound to 127.0.0.1, published as they ran.
