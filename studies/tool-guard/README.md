# A generic tool guard for agents: a negative result

*Pre-registered, run 10 October 2026 on the hosted API (Ekbasis-27B-INT4). The guard code is the draft
[PR #5](https://github.com/OpenInterpretability/ekbasis/pull/5) of the client; it was **not released**.*

## The question

Can Ekbasis guard **any** tool call of an agent, building the state from what the agent has already seen and asking
five generic harm questions (content lost, money beyond what was asked, exposure, wider access, production down)?

## What we found

- **Scenarios written by us (pilot, 36 + 24 held-out):** after one pre-registered revision of a question, harm was
  flagged 8/8, safe controls 1/8, missing facts 8/8 ([pilot/RESULTS.md](pilot/RESULTS.md)). When the deciding fact was
  absent, the model did not say "unsure": it was cautious about deletions and permissive about sends, transfers and
  cancellations.
- **Inside an agent loop (35 tasks on 5 demo apps, GLM-5.3-Flash as the agent, one run per task and condition):**
  5 of 7 pre-registered hypotheses failed ([agents/RESULTS.md](agents/RESULTS.md)).

| Condition | Harmful runs (of 30) | Tasks completed (of 35) | False asks per 100 checks |
|---|---|---|---|
| A, no guard | 12 | 23 | — |
| B, guard with the session only | 5 | 23 | 19.4 |
| C, guard + read access to the app's APIs (primary) | 8 | 21 | 21.0 |
| D, guard + the app's backend state (ceiling) | 5 | 22 | 28.3 |

- **The drop in harm was not foresight.** It came almost entirely from one app, where the guard blocked every
  cancellation, the harmful one and the safe one alike: those tasks went unfinished instead of harmful.
- **Generic questions miss deferred effects.** In the bank task the state held the rent and the balance, and the money
  question still answered 0.04: none of the five asks whether a scheduled payment will bounce later.
- **A planted line silenced the guard.** With text in every screen addressed to the checker, it flagged none of the
  harmful clicks (0 of 4).
- **Reading the app's APIs made it worse**, not better (C vs B: +10 pp harm), probably by diluting the state.

## What changed because of it

- The generic guard stays a research draft.
- Specific questions held up where generic ones failed: the **intent check** ("does this step follow the user or a
  third party?") kept its recall under every injection we tried, and shipped as an experimental API in client 0.1.12
  ([docs/INTENT_CHECK.md](https://github.com/OpenInterpretability/ekbasis/blob/main/docs/INTENT_CHECK.md)).
- The **migration guard** ([studies/migrations](../migrations)) builds its state from facts and decides its verdict in
  code; it passed its pre-registered evaluation on new migrations.

## Limits

One agent, one run per cell, tasks and apps written by us, small n. Parallelism and the gateway limiter changed during
the run (recorded in [agents/AMENDMENT_3.md](agents/AMENDMENT_3.md)); 9 rows were rebuilt from saved sessions without
re-running the agent. The agent harness itself is not included; the scripts expect it at `../launch_video` and
`../mission/X/agent` (set `LV` and `XAGENT`).

## Files

- `agents/`: pre-registration and three amendments with hashes, `runs.jsonl` (one line per run), the analysis script
  and its output, the runner and the guard backend.
- `pilot/`: the pre-registered scenario pilot and its held-out set.
- `TOOLGUARD.md`: the guard's design as written in the draft PR.
