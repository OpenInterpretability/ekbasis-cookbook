# Use-case map: where the consequence model earns its keep

All numbers measured on **Ekbasis-27B-INT4** (4× B200, TP4, co-tenant with a production LLM, October 2026). Every scenario has a hand-verified ground truth; the suites are re-runnable from [`examples/`](../examples/).

## Score by domain (171 scenarios across 21 domains, two suites)

**Suite 1** (85 scenarios — everyday apps + ops):

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

**Suite 2** (86 scenarios — infrastructure, security and data ops):

| domain | result | what it nails |
|---|---|---|
| identity/access (10) | **10/10** | secret committed to public history survives later removal, rotate-without-revoke leaves the leaked key live, `write:packages` token blast radius, repo flip to public, owner-level service account |
| docker (10) | **10/10** | volume rm / `compose down -v` / `prune -a --volumes` destroy data, deleted registry tag breaks pulls, hot-patch lost on rebuild, laptop `latest` overwrite, port conflicts |
| network (9) | **9/9** | `ufw reset` wipes all rules, security group 0.0.0.0/0 exposes the DB, DNS record deletion = TTL-bounded outage, expired cert, NAT route removal kills private-subnet egress |
| cloud storage (9) | **9/9** | bucket `--force` delete, schema change under a daily consumer, **versioning keeps the old object recoverable**, lifecycle vs compliance retention, AMI depends on its snapshot (does not copy), unencrypted cross-region copy of PII |
| org/team (8) | **8/8** | org deletion takes all repos, demote-mid-incident blocks the hotfix push, branch protection off = anyone force-pushes main, webhook deletion stops releases, SSO disable = lockout |
| git deep (9) | **9/9** | rebase of a shared branch diverges the teammate, filter-repo forces re-clones, re-tagging splits the meaning of v2.0, **LFS: replacing the file with a pointer does NOT delete the weights**, amend of a pushed commit is rejected, `clean -fdx` removes ignored `.env` |
| pipelines (8) | **8/8** | `echo $SECRET` in public logs, `pull_request_target` fork exfiltration, `on: push` deploys junk branches to prod, non-idempotent re-run double-counts, `action@main` supply-chain break |
| data pipelines (8) | **8/8** | partial overwrite looks normal in analytics, backfill without idempotency double-counts, checkpoint deletion reprocesses 48h, temp table slows prod, no-transaction ETL = inconsistent state |
| ML ops (7) | **7/7** | registry alias overwritten pre-eval serves the unvalidated model, stale feature store degrades rankings, checkpoint-best overwritten = lost, eval leakage inflates the report, T4 "savings" miss the deadline |
| jobs/time (8) | **8/8** | no-lock manual trigger races, kill with/without checkpoints (30 min vs 5.5 h), crontab in **local** time (TZ change moves the run), `at` jobs die on reboot |

**Combined total: 168/168 scored correct (100%) + 3 ambiguous-by-design cases answered sensibly; mean latency ~0.55 s.**

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
pip install ekbasis
export EKBASIS_URL=http://your-server:8010
python examples/run_suite.py examples/scenarios_intensive.jsonl
```
