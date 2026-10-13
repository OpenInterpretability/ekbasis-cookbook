# Check a plan before your agent runs it

An agent often proposes several actions at once: a few tool calls, a script, a pipeline. This recipe checks the whole
batch before anything runs, the "look when unsure" way:

1. Ekbasis forecasts every prefix of the batch from the state as it is now (in parallel, one request each).
2. If every prefix is harmless with confidence ≥ 0.9, the whole batch runs.
3. Otherwise the steps before the first flagged or uncertain one run, the real state is read again, and the rest is
   checked on it. A step still flagged on the real state does not run: ask the user, or take a safer way.

## Run it in a minute

Each example runs against the hosted API on a tiny simulated server (photos and a rebuildable cache), asked to "free
some disk space" with a plan that would also delete the photos.

```bash
export EKBASIS_API_KEY=ekb_...            # https://openinterp.org/console

# Python (ekbasis >= 0.1.28)
pip install -U ekbasis
EKBASIS_URL=https://openinterp.org/api/v1 python agent_batch.py

# TypeScript / JavaScript (npm ekbasis >= 0.2.1; CommonJS or ESM)
npm install ekbasis tsx
npx tsx agent_batch.ts
```

Both print:

```
  ran: du -sh /srv/shop/*
  ran: rm -rf /srv/shop/cache/*
stopped before step 3: Ekbasis flags data_lost, unasked_deletes, breaks_later it -> ask the user or take a safer way
```

## Wire it to your agent

Three things are yours to write; the rest is `run_plan` / `runPlan`:

| | What | Example |
|---|---|---|
| `RULES` | how this system works, in a few plain sentences, including what is permanent | "rm -rf deletes permanently; there is no backup" |
| `observe()` | how things stand now, as text: what exists, what is serving, what holds data | read it from your system before each check |
| `execute(actions)` | run some of the actions | your tool-call executor |

Then, where your agent loop would run the model's tool calls, call `guard_batch(user_request, actions)` instead. Pass
the user's request in their own words: the preset harm questions (`harms()`) ask about harm that the request does
**not** ask for, so "delete the old uploads" is not flagged when the user asked for exactly that.

## From a shell, CI or another language

```bash
ekbasis plan-check --rules @rules.txt --state @state.txt --request "Free some disk space on the server." \
    "du -sh /srv/shop/*" "rm -rf /srv/shop/cache/*" "rm -rf /srv/shop/uploads/*" "df -h"
# exit 0: run every step · exit 2: run the first N, then look · exit 3: cannot foresee (treat as risky)
```

`--json` prints each step's probabilities; `--ask "...?"` adds your own yes/no harm question (yes = the harm). Any
language can call the HTTP API directly: [OpenAPI](https://openinterp.org/api/v1/openapi.json).

## Notes

- **The preset questions** (`data_lost`, `outage`, `unasked_deletes`, `breaks_later`) are worded like the ones measured
  in our Kubernetes studies, made general. In another domain, try them on a few of your own cases first, and add your
  own questions for the harms specific to your system.
- **Cost:** one request per step checked, each reading the state and the steps so far. Measured on this example: 4
  requests of 1,104–1,224 input tokens (4,680 in all, none generated), US$0.0014 at US$0.30 per 1M input tokens
  ([pricing](https://openinterp.org/ekbasis/pricing)). Longer states and plans cost proportionally more.
- **Where the answer must be exact** (a running total crossing a limit, a command that fails), check it in code too:
  confidence alone does not catch confident errors.
- **When the API cannot answer** (no credits, rate limited, down) the clients raise `CannotJudge`: treat the batch as
  unchecked, never as safe. Live uptime and daily quality: [API status](https://openinterp.org/ekbasis/status).
