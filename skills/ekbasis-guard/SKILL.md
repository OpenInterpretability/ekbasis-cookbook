---
name: ekbasis-guard
description: Consult the Ekbasis consequence model BEFORE destructive or irreversible actions (git history work, rm on important data, database DDL/DML without WHERE, killing processes, deleting cloud resources, sending messages to many people). Use when about to run a command that could lose work, break production, or leak information — especially when the agent itself is unsure whether the action is safe.
---

# Ekbasis guard: foresee before you act

Ekbasis is a consequence model: given the **state** of the world and an **action**, it predicts what happens (calibrated, one forward pass, no LLM reasoning). This skill tells you when to consult it and how to read the answer.

## When to consult

Consult **before** any action that is hard to undo, in any of these classes:

- **git**: history rewrites (`reset --hard`, `checkout -f`, `branch -D`, `push --force`, `filter-branch`), anything that touches uncommitted work or unreachable commits
- **files**: `rm`/`mv`/`>` over data that has no backup or is not in git; globs; anything touching directories you did not create this session
- **databases**: `DROP`, `TRUNCATE`, `DELETE`/`UPDATE` without WHERE, migrations (up AND down) on production
- **processes**: `kill` of a PID you did not create yourself this session (stale notes lie — check `ps` first)
- **cloud/infra**: deleting namespaces/PVCs/secrets, scaling down before peaks, switching contexts, `apply` with the wrong `--context`
- **communication**: sending to more than ~5 people, reply-all, forwarding outside the original circle

If the action only creates new files, reads state, or is trivially undoable — **skip the consult**. Over-asking trains the human to click through.

## How to consult

**CLI (when it is a git or shell command):**

```bash
EKBASIS_URL=http://your-server:8010 ekbasis git-check -- "git reset --hard"
EKBASIS_URL=http://your-server:8010 ekbasis shell-check -- "rm -rf $TMPDIR/*"
```

Exit codes: `0` ok · `2` RISKY (may lose work) · `3` cannot judge (**treat as risky**). `&&` chains: `ekbasis git-check -- "git checkout main" && git checkout main`.

**Raw API (when the action is not a shell command — calendar, mail, cloud, plans):**

```bash
curl $EKBASIS_URL/v1/systemone -H "Content-Type: application/json" -d '{
  "state": "<what exists now, the facts that matter>",
  "questions": {"q": {"type": "choice", "instructions": "What happens if ...?",
                      "options": ["<bad outcome>", "<good outcome>"]}}}'
```

Question types: `choice` (pick among outcomes), `noul`/`boolean` (yes/no loss question, returns `probability` of true), `score` (how many / how much). Several questions about one state go in **one request** (shared prefix, ~0.6 s for 3).

## How to read the answer

- **RISKY / p(bad) ≥ 0.5**: pause, show the human the reason, do not proceed without confirmation.
- **ok / p(bad) < 0.2**: proceed.
- **cannot judge**: the state is missing a fact — go **collect the missing fact** (read the file, check `ps`, look at the calendar) and ask again. Do not guess.
- **Confidence is calibration, not decoration**: 0.59–0.84 on an ambiguous state means *the model honestly lacks information* — the same signals it shows at 0.99 when the world is fully described. Treat < 0.9 on a destructive action as "check first".

## The state you send

Write the facts the action touches, not the whole world: the balance, the file list, the free space, the branch/remote divergence, the PID map, the current context. The git client already builds this for you (`git-check`). For raw API calls, 3–8 concrete facts beat 3 pages of context. States over ~30k tokens are refused.

## Measured reference (Ekbasis-27B-INT4, October 2026)

- Classic git losses: 8/8 flagged at 98–99%; 9 safe commands: 0 false alarms
- 85-scenario intensive suite across money/disk/mail/calendar/cloud/db/deploy/shell/numeric/plans: 83/83
- Known gap: `git push --force` against a diverged remote (remote loss is not flagged today) — double-check force-pushes yourself
- Latency: ~0.5 s per check on GPU, 5–12 s on Mac MLX

## Chaining in scripts

```bash
ekbasis git-check -- "git reset --hard" || { echo "guard says: check first"; exit 2; }
```
