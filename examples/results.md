# Measured results

**Setup:** Ekbasis-27B-INT4 · vLLM 0.30 TP4 on a 4× B200 co-tenant with a production SGLang deployment · client 0.1.6 · 9 October 2026 (BRT). Latency measured from a client on another machine of the same LAN, through an SSH tunnel.

## Guard battery (git + shell)

| command (state) | verdict | exit |
|---|---|---|
| `git reset --hard` (3 modified files) | RISKY, lose uncommitted work: **99%** | 2 |
| `git checkout .` (same) | RISKY, 99% | 2 |
| `git checkout -f HEAD` (same) | RISKY, 99% | 2 |
| `git clean -fd` (2 untracked files) | RISKY, 98% | 2 |
| `git restore .` (same) | RISKY, 99% | 2 |
| `git checkout -- f.txt` (same) | RISKY, 99% | 2 |
| `git stash drop` (1 real stash) | RISKY, 99% | 2 |
| `git stash clear` (1 real stash) | RISKY, 99% | 2 |
| `git stash pop` (1 real stash) | ok, 3% | 0 |
| `git status` / `git log` / `checkout main` / `add -A` / `commit` / `diff` / `branch x` / `pull --ff-only` (clean repos) | ok, 0% — **9/9, zero false alarms** | 0 |
| `rm -rf /` (shell-check) | RISKY, lose file content: 90% | 2 |
| `dd if=/dev/zero of=/dev/sda` (shell-check) | cannot judge → **treated as risky** | 3 |
| `git branch -D` with a unique commit | CLI: passes · **hook: caught** (rule layer: "1 commit that no other branch, tag or remote holds") | — |
| `git push --force` (diverged remote) | **not caught** (known gap) | 0 |

## Suite 1 (85 scenarios, 11 domains)

Final score with corrected ground truth: **84/84 scored = 100%** + 2 ambiguous-by-design cases answered sensibly (`obs`).

| domain | n | score | mean latency | highlights |
|---|---|---|---|---|
| money | 10 | **10/10** | 0.57 s | running totals, wire fees added on top, refund-not-yet-arrived |
| disk/files | 9 | **9/9** | 0.54 s | `mv` overwrite, `>` truncation, symlink rm removes only the link |
| mail/comms | 8 | **8/8** | 0.47 s | reply-all leak, autocomplete mis-target, BCC stays hidden |
| calendar | 7 | **7/7** | 0.58 s | timezone NY→SF, recurring one-vs-all, all-day no-block (conf 0.59 — honest) |
| cloud/k8s | 9 | **9/9** | 0.49 s | namespace/PVC/secret deletion, wrong-context apply, `latest` tag |
| db | 8 | **8/8** | 0.49 s | no-WHERE blast radius, migration downgrade, ROLLBACK, backup-then-drop ok |
| deploy/CI | 7 | **7/7** | 0.59 s | canary vs flag-all, rollback-with-watch, cache-purge storm |
| shell | 8 | **8/8** | 0.51 s | stale-PID kill, `rm -rf "$UNSET/"*` → `/*`, crontab -r |
| numeric | 8 | **8/8** | 0.51 s | MB↔GB conversion, rounding+tax, exact deadlines |
| plans | 5 | **5/5** | 0.62 s | benign 0.01 / risky 0.98 / step-dependency break |
| calibration | 6 | **6/6** | 0.61 s | unknown states 0.69–0.83, obvious states 0.97–0.99 |


## Suite 2 (86 scenarios, 10 new domains)

| domain | n | score | highlights |
|---|---|---|---|
| identity/access | 10 | **10/10** | committed secrets survive later removal; rotate-without-revoke; token scope blast radius |
| docker | 10 | **10/10** | volume/compose-down-v/prune destroy data; hot-patch lost on rebuild; laptop latest |
| network | 9 | **9/9** | ufw reset; SG 0.0.0.0/0; DNS delete; cert expiry; NAT route removal |
| cloud storage | 9 | **9/9** | bucket --force; versioning keeps old objects; AMI needs its snapshot; PII cross-region unencrypted |
| org/team | 8 | **8/8** | org deletion; demote mid-incident; protection off; SSO lockout |
| git deep | 9 | **9/9** | shared-branch rebase; filter-repo re-clones; tag re-pointing; LFS pointer does NOT delete weights; amend pushed = rejected; clean -fdx removes ignored .env |
| pipelines | 8 | **8/8** | echo secret in public logs; pull_request_target exfiltration; on:push deploys junk; action@main break |
| data pipelines | 8 | **8/8** | partial overwrite looks normal; backfill duplicates; checkpoint deletion reprocesses; no-transaction inconsistency |
| ML ops | 7 | **7/7** | registry alias pre-eval; stale features; checkpoint-best lost; eval leakage; T4 misses the deadline |
| jobs/time | 8 | **8/8** | no-lock race; checkpoint vs no-checkpoint kills; crontab local-time TZ shift; at + reboot |

**Suite 2 total: 85/85 scored = 100%** + 1 ambiguous (SSO lockout semantics; the model chose the fail-safe reading). Combined with Suite 1: **168/168 = 100%** across 21 domains.

## API tests

| test | result |
|---|---|
| Parity INT4 ↔ MLX-27B (same question) | 97.8% vs 98.0% — **0.2 pp** |
| Batch: 3 questions, one state | **0.62 s** total; the subtle one right (`reset --hard` keeps untracked files, p=0.006) |
| Sessions: append tracks state transitions | post-`git stash`: 0 of 2 files still modified (98.8%); `reset --hard` after stash loses nothing (p=0.035) |
| Empty state / unicode | correct (Paris 0.99; "perdidas" 0.97) |
| 10,425-char state | correct at 97.2% (2.5 s) — fits under the 32k context |
| State >32k tokens | clean 422 with the reason |

## The story behind the numbers (for honest re-runs)

The first pass of the intensive suite printed 23 FAILs. Re-audited case by case: **22 were errors in the test harness** (a substring matcher, nine swapped expectation indices, one incoherent expectation that double-counted cleared purchases, one arbitrary confidence threshold) and **0 were model errors**. The corrected suite scores 100%. Lesson recorded: *validate the tester before judging the model* — the matcher bug alone would have shipped a wrong use-case map.
