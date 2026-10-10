# Agent study: the same 47 tasks, run three times (twice through the hosted API)

47 in-lab tasks across 7 demo apps (calendar, chat, cloud, drive, files, mail, shop): 42 with a harm path and 5
controls. Each task is run in two conditions by GLM-5.3-Flash as the agent: `blind` (no Ekbasis) and `see`
(it can ask Ekbasis what an action will do before acting). The study was run three times with the same tasks:

- **rep1** (Oct 6): Ekbasis-27B-INT4 called directly on the model server.
- **rep2, rep3** (Oct 10): the same model called through the hosted API (`https://openinterp.org/api/v1`) with a
  normal API key, so these two repetitions also test the product path: authentication, prepaid balance, metering.

The run label `seed` in the files is only a label: nothing in the agent or the model is seeded, so the three runs
are independent runs of the same tasks and agent: they show the result holds from run to run, not across new tasks.

| repetition | harmful runs, blind → see | difference [95% CI] | task success, blind → see |
|---|---|---|---|
| rep1 (direct) | 23/47 → 3/47 | −42.6 pp [−57.4, −27.7] | 24/47 → 43/47 |
| rep2 (hosted API) | 24/47 → 0/47 | −51.1 pp [−66.0, −36.2] | 23/47 → 46/47 |
| rep3 (hosted API) | 26/47 → 0/47 | −55.3 pp [−70.2, −40.4] | 21/47 → 46/47 |
| **average of the three runs** | | **−49.6 pp [−61.7, −37.6]** | |

Confidence intervals: bootstrap over tasks (10,000 resamples, seed 7); when the repetitions are pooled, a task is
the resampling unit (its difference averaged over the repetitions first). Recompute everything with
`python recompute.py` (output in `recompute_output.txt`).

**The product path in rep2 and rep3:** 224 calls through the hosted API, no 401/402/403/5xx; the metered tokens
returned with every answer matched the model's own count on every call, and the account balance fell by exactly their
sum (105,180 tokens, $0.0042 at $0.04 per 1M). Client-side latency per call: p50 1.43 s at the time, since cut to
about 0.67 s by caching the key check (Oct 10).

**Limits.** The apps and tasks were built by us and keep the consequence hidden from the agent's screen, which is
where a consequence model helps most; real apps are harder (see the paper's real-apps results, where the gain held
for Claude Sonnet but not for Claude Haiku). One agent model. Files: `rep1_runs.jsonl`, `rep2_runs.jsonl`,
`rep3_runs.jsonl`, one line per run.
