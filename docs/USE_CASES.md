# Use-case map: where the consequence model earns its keep

All numbers measured on **Ekbasis-27B-INT4** (4× B200, TP4, co-tenant with a production LLM, October 2026). Every scenario has a hand-verified ground truth; the suites are re-runnable from [`examples/`](../examples/).

## Score by domain (85 scenarios, intensive suite)

| domain | result | what it nails |
|---|---|---|
| git/shell guard (separate battery) | **8/8 losses @ 98–99%, 0 FA on safe** | the core guard use case |
| money (10) | **10/10** | running totals ($100 − 4×$12.30), fees added to wires, daily limits, overdraft semantics, refund timing (not-yet-arrived ≠ available), split payments |
| disk/files (9) | **9/9** | only-copy vs backed-up, `mv` overwrite, `>` truncation, glob rm, `chmod 000 /etc`, **rm on a symlink removes the link, not the target** |
| mail/comms (8) | **8/8** | reply-all leaks to external clients, autocomplete mis-targets, payroll attachment to company list, placeholder text sent, BCC stays hidden in reply-all, auto-replies go to the sender (no loop) |
| calendar (7) | **7/7** | overlap conflicts, recurring: one occurrence vs the series, timezone arithmetic (NY 9 AM → SF 6 AM), room double-booking, all-day events don't block (answers at conf 0.59 — honest) |
| cloud/k8s (9) | **9/9** | scale-down before peaks, namespace/PVC/secret deletion, wrong-context apply, `latest` tag mutated by a bad rebuild, drain of the only node, reserved-instance commitments |
| db (8) | **8/8** | DROP/TRUNCATE/DELETE-no-WHERE/UPDATE-no-WHERE blast radius, migration downgrade loses column data, ROLLBACK discards, backup-then-drop is approved |
| deploy/CI (7) | **7/7** | canary vs flag-for-all, rollback-with-watch, blue-green switchback, cache-purge origin storm, ALTER lock during peak |
| shell (8) | **8/8** | stale-PID kill hits the live server, **`rm -rf "$UNSET/"*` → `/*`**, sudo rm of a data dir, `>>` vs `>`, crontab -r kills the backup silently |
| numeric (8) | **8/8** | unit conversion (4,000 MB < 5 GB), rounding+tax over budget, deadline-to-the-minute, seat counting |
| plans (5) | **5/5** | multi-step: benign plan passes at 0.01, risky plan flagged at 0.98, step-dependency breakage, partial-failure state |
| calibration (6) | **6/6** | unknown states → conf 0.69–0.83 (honest uncertainty); obvious states → 0.97–0.99 |

**Total: 83/83 scored correct (100%), 2 ambiguous cases answered sensibly, mean latency 0.53 s.**

## Where the guard changes behavior (the daily-use loop)

| action class | what the guard does | cost |
|---|---|---|
| destructive-but-recoverable (reset --hard with stash/backup) | flags the loss, human confirms | 2 s |
| destructive-irreversible (only-copy rm, DROP without backup) | flags at 0.93–0.99 | 2 s |
| safe-but-scary-looking | silent (0 false alarms in 9 measured) | none |
| state unknown | says so (conf < 0.85) → go collect the missing fact | 1 s |

## Weak spots measured (design around them)

1. **`git push --force` with a diverged remote** — the model reads the local state and answers "ok" (and predicts the command *fails*, when force-push actually succeeds and overwrites the remote). Remote loss is outside the current question framing and outside the client's ref-simulation rules. **Fixed in client 0.1.7:** the hook now asks when a force-push would overwrite commits the remote holds that the local branch does not (`--force-with-lease` stays safe by design).
2. **`shell-check` is a prototype** — `curl … | bash` and `kill -9 -1` pass today; catastrophic shell patterns like `dd of=/dev/sda` return "cannot judge" (fail-closed, exit 3 — treated as risky).
3. **Very large states (>32k tokens)** are refused (clean 422). The right pattern: send the *slice the action touches*, not the whole world — the git client does this (8 files, 12 branches max).

## What the numbers say the model is FOR

- **The best measured use case: the pre-action guard for irreversible actions**, with the human in the loop (hook `ask` mode). It is right about classic losses 98–99% of the time, wrong-answer rate on safe commands ≈ 0.
- **The second: agent decision support** — batch questions over one state (0.62 s for 3), sessions for evolving state; this is the pattern for agents working on long tasks.
- **Calibration is the feature, not a bug**: the confidence value is usable as a routing signal (≥ 0.9 proceed, < 0.9 check first).

## Reproduce

```bash
pip install "git+https://github.com/OpenInterpretability/ekbasis"
export EKBASIS_URL=http://your-server:8010
python examples/run_suite.py examples/scenarios_intensive.jsonl
```
