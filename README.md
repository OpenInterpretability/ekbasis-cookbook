# Ekbasis Cookbook

Recipes, skills, hooks and measured results for using [Ekbasis](https://github.com/OpenInterpretability/ekbasis) — the open world model for agents — as a **guard for destructive actions** and a **foresee API for agent decisions**.

Every number in this repo was measured, not estimated. The suites are in [`examples/`](examples/) and re-runnable against any Ekbasis server.

**Model:** Ekbasis-27B-INT4 (vLLM ≥ 0.30, tensor-parallel) · Papers: [Look When Unsure, Check When Sure](https://doi.org/10.5281/zenodo.23146970) · [When Does a Consequence Model Make AI Agents Safer?](https://doi.org/10.5281/zenodo.23197341)

---

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
pip install "git+https://github.com/OpenInterpretability/ekbasis"
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
