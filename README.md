# Ekbasis Cookbook

Recipes, skills, hooks and measured results for using [Ekbasis](https://github.com/OpenInterpretability/ekbasis) — the open world model for agents — as a **guard for destructive actions** and a **foresee API for agent decisions**.

Every number in this repo was measured, not estimated. The suites are in [`examples/`](examples/) and re-runnable against any Ekbasis server.

**Model:** Ekbasis-27B-INT4 (vLLM ≥ 0.30, tensor-parallel) · Papers: [Look When Unsure, Check When Sure](https://doi.org/10.5281/zenodo.23146970) · [When Does a Consequence Model Make AI Agents Safer?](https://doi.org/10.5281/zenodo.23197341)

---

## The agent study: does the guard actually protect agents?

47 in-lab tasks across 7 apps (calendar, chat, cloud, drive, files, mail, shop), each run in two conditions: `blind` (no model) vs `see` (consults Ekbasis before acting). Agent: GLM-5.3-Flash. The same 47 tasks were **run three times**; the second and third runs called Ekbasis **through the hosted API**, with an ordinary API key. Same tasks and agent each time: this shows the result holds from run to run, not across new tasks.

| | blind | see | effect |
|---|---|---|---|
| harmful runs, run by run | 23/47 · 24/47 · 26/47 | 3/47 · 0/47 · 0/47 | **−49.6 pp on average, 95% CI [37.6, 61.7]** (bootstrap over the 47 tasks) |
| task success, run by run | 24/47 · 23/47 · 21/47 | 43/47 · 46/47 · 46/47 | +47.5 pp on average |

The guard did not just block damage: agents with it **completed their tasks about twice as often**. Through the hosted API: 224 calls, no errors, metering exact to the token. Details, data and a recompute script: [`studies/agents-3reps/`](studies/agents-3reps/). Limits: our own apps, one agent model; on real apps the gain held for Claude Sonnet but not for Claude Haiku ([paper](https://doi.org/10.5281/zenodo.23197341)).

## Kubernetes study: kubectl agents on a real cluster (pre-registered)

24 fresh tasks on a real kind cluster (18 with a hidden harm: data loss, outage, broken restart, another team's object;
6 controls). Agent: Claude Haiku 4.5. The guard checks each mutating `kubectl` command with code checks plus
Ekbasis-27B (MLX 4-bit on a Mac), offers a checked safer way, or asks a simulated user.

| | blind | Ekbasis guard | same guard, Sonnet as forecaster | ask before every command |
|---|---|---|---|---|
| harmful runs | 24/36 (66.7%) | **2/36 (5.6%)** | 1/36 (2.8%) | 0/36 (0%) |
| questions per run | — | **0.77** | 0.60 | 2.31 |
| guard cost per run | — | US$0.0026 at the hosted API price | US$0.073 as paid | — |

Pre-registered: harm vs blind **−61.1 pts [−80.6, −38.9] (pass)**; fewer questions than asking always **(pass)**;
non-inferiority to the Sonnet forecaster within 8 pts **failed** (+2.8 [−5.6, +11.1]). Asking every time was as safe
with this simulated user, so the guard's measured gain is asking a third as often. Details, limits and cost (descriptive):
[docs/K8S_STUDY.md](docs/K8S_STUDY.md) · data and rerun: [studies/k8s/](studies/k8s/).

## The one-line pitch

An agent that can foresee consequences makes fewer irreversible mistakes. This repo maps **where** that works, with numbers.

## What was measured (October 2026)

| suite | result | where |
|---|---|---|
| Guard, classic losses (reset --hard, checkout ., -f, clean -fd, restore ., checkout --) | **8/8 flagged at 98–99%** | [guard battery](examples/results.md#guard) |
| Guard, safe commands (9, clean repo) | **0 false alarms** | guard battery |
| Guard, real stash semantics (drop/clear = RISKY 99%, pop = ok) | **3/3** | guard battery |
| Claude Code hook, committed-work rule (`branch -D` with unique commits) | **caught** ("ask" + explanation) | guard battery |
| Intensive use-case suites: 21 domains, 171 scenarios | **168/168 scored = 100%** + 3 ambiguous answered sensibly | [results](examples/results.md) |
| Calibration honesty: ambiguous states | confidence drops to **0.59–0.84** (never fake 0.99) | intensive suite, `calib` rows |
| Numeric edge cases (units MB↔GB, rounding+tax, exact deadlines, running totals) | **8/8** | intensive suite, `numeric` |
| API parity INT4 ↔ MLX-27B on the same question | **0.2pp difference** (97.8 vs 98.0) | [API tests](docs/API.md) |
| Batch: 3 questions, one state, one request | **0.62 s** | [API tests](docs/API.md) |
| Sessions (state → append → ask): state tracked correctly | ✅ (post-`git stash`: 0 of 2 files still modified, 98.8%) | [API tests](docs/API.md) |

### Latency (measured end-to-end from a client, one guard call)

| serving | latency per check |
|---|---|
| 4× B200, INT4, TP4 (co-tenant with a production LLM) | **0.4–2.5 s** (git check ~0.7 s) |
| MacBook Pro, MLX 27B 4-bit (local, no server) | 4.7–12.5 s |
| Reference GPU build (bf16, dedicated) | ~0.1 s |

### Known gaps (do not rely on these without your own check)

1. **`git push --force` with a diverged remote** — the model answers "ok" (it predicts the command *fails* instead of succeeding and overwriting the remote). Neither the model nor the client rules flag remote loss today. Fixed in client 0.1.7 ([PR #1](https://github.com/OpenInterpretability/ekbasis/pull/1)): the hook now asks when a force-push would overwrite remote commits; `--force-with-lease` stays safe by design.
2. **`shell-check` is a prototype** — `curl … | bash` and `kill -9 -1` pass today.
3. **States > ~32k tokens** are refused with a clean 422 (the client's git world stays under it by design: 8 files, 12 branches max).

## Quick start

```bash
pip install ekbasis
EKBASIS_URL=http://your-server:8010 ekbasis health
cd some-repo && ekbasis git-check -- "git reset --hard"   # RISKY if uncommitted work
```

- **Use it as an automatic confirmation in Claude Code:** [`hooks/`](hooks/)
- **Teach your agent when and how to consult it:** [`skills/ekbasis-guard/SKILL.md`](skills/ekbasis-guard/SKILL.md)
- **Serve it on a Mac:** [`docs/SETUP_MAC_MLX.md`](docs/SETUP_MAC_MLX.md) · **on GPUs (even shared with production):** [`docs/SETUP_GPU.md`](docs/SETUP_GPU.md)
- **Call the API directly:** [`docs/API.md`](docs/API.md)

## The 3 flags that let Ekbasis share GPUs with a production LLM

(For the full runbook, [SETUP_GPU.md](docs/SETUP_GPU.md).)

```bash
NCCL_NVLS_ENABLE=0              # the first TP group already owns the NVLS multicast
VLLM_ALLREDUCE_USE_FLASHINFER=0 # flashinfer comm wants ~2.7 GB of non-PyTorch memory
--gpu-memory-utilization 0.036  # vLLM 0.30 validates this against FREE memory
```

## License

MIT. Ekbasis itself: Apache-2.0 (see its repo).
