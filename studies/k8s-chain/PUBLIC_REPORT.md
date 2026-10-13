# Guarding an agent's pipelines on Kubernetes: Ekbasis vs a large LLM as the judge

Four pre-registered studies, October 2026. Agent: Claude Haiku 5.5, on a real Kubernetes cluster (kind). Every
number here is recomputed from the files in this folder by [`recompute_chain3.py`](recompute_chain3.py) (v3) and by the
sealed [`chain/analyze_chain.py`](chain/analyze_chain.py) (v1, v2) and by [`recompute_chain4.py`](recompute_chain4.py) (v4).

## The setup

The agent is asked to run multi-step pipelines (`bash pipeline.sh`, a few to a dozen `kubectl` steps). In 12 of the 18
tasks one step hides a harm the user did not ask for: data on a volume deleted, a serving Service left with no ready
pods, another team's object removed, a workload that will not start again. 6 tasks are controls with no harm.

The **chain guard** ("look when unsure" for a pipeline) forecasts every prefix of the pipeline before it runs. If every
prefix is harmless with confidence, the pipeline runs; otherwise the steps before the first flagged or uncertain one
run, the real cluster is read again, and the rest is checked on it. A step still flagged asks the user (simulated).

## v3: Ekbasis vs GLM-5.3 as the judge (108 runs: 18 tasks × 3 arms × 2 seeds)

| | no guard | chain guard + Ekbasis | chain guard + GLM-5.3 |
|---|---|---|---|
| Harmful runs (of 24) | 9 | **0** | **0** |
| Checking time per run (median) | — | **22.4 s** | 357.2 s |
| Whole agent run (median) | 21 s | 53 s | 397 s |
| Cost per run | — | **$0.045** (Ekbasis API price) | $0.44 (at Claude Sonnet 5.5 API prices) |
| Judge calls with no usable answer | — | **0 of 274** | 51 of 386 |
| Tokens per run, read / generated | — | 150,982 / 0 | 28,545 / 38,345 |
| Tasks completed (of 24) | 6 | 10 | 14 |
| Controls completed (of 12) | 12 | 12 | 12 |

GLM-5.3-Flash is a large general LLM we serve; it got the prompt the Claude Sonnet forecaster used in our earlier
Kubernetes study (default reasoning, temperature 0, up to 4,000 tokens). The guard, tasks and agent were identical.

**Pre-registered hypotheses** ([`chain3/PREREG_chain3.md`](chain3/PREREG_chain3.md), sealed with the code by SHA-256
before the analyzed runs):

| | Result |
|---|---|
| H1 same safety (Ekbasis harm ≤ GLM harm + 2) | 0 vs 0 — **pass** |
| H2 faster (one-sided Wilcoxon, median ratio ≥ 5) | 15.9×; Ekbasis faster in 32 of 36 pairs, 4 ties at zero; p = 4×10⁻⁷ — **pass** (see the correction below) |
| H3 cheaper (one-sided Wilcoxon) | 10×; same 32 of 36; p = 4×10⁻⁷ — **pass** (see the correction below) |
| H4 fewer missing answers | 0 vs 51 — **pass** |

**A correction, declared.** The sealed analysis script printed p = 1 for H2 and H3. Its Wilcoxon function, copied from
the v1 script, used the wrong tail in its normal approximation (it returns P(W ≤ w) where the one-sided test needs
P(W ≥ w)); the exact branch, used for small samples, is right. The correction was made after seeing the numbers, so the
sealed output is published as it is ([`chain3/results/analysis_g_sealed.txt`](chain3/results/analysis_g_sealed.txt))
and the corrected p-values are checked three ways in `recompute_chain3.py`: the fixed formula, SciPy's
`wilcoxon(alternative="less")`, and a sign-flip permutation test (p ≈ 5×10⁻⁶ from 200,000 draws). The same bug in v1's
analysis changes one p-value (H3 interruptions: 0.86 → 0.14) and no verdict; v2 used the exact branch.

**Other deviations** ([`chain3/DEVIATIONS_chain3.md`](chain3/DEVIATIONS_chain3.md), each written before the numbers it
could change, except the correction above):
- runs in parallel raised from 3 to 5 after 57 runs, to finish sooner. Seconds per judge call before → after: Ekbasis
  2.79 → 2.73, GLM 30.1 → 23.6 (the GLM got faster, so the change did not favor Ekbasis); H2 on the runs before the
  change only: 20 pairs, 12.8×, p = 0.0002;
- 14 Ekbasis-arm runs were invalidated for 30 minutes by a validation bug we deployed in our own API gateway (it refused
  a valid question type); none was recorded as a result, and they were run again
  ([`invalid_g_gateway_bug.jsonl`](chain3/results/invalid_g_gateway_bug.jsonl)).

## v4: both judges forecasting in parallel (72 runs: 18 tasks × 2 judges × 2 seeds)

v3 forecast a pipeline's prefixes one by one, which is slower for the large LLM. v4 changes only that: both judges
forecast the prefixes in parallel waves of 5 (as `ekbasis.check_plan(parallel=5)` does), with the decision read in
order, unchanged. Time is now the wall clock of each guard call (`guard_ms`, which also includes the code checks and the
cluster reads, the same for both judges). Pre-registration and code sealed before the runs
([`chain4/PREREG_chain4.md`](chain4/PREREG_chain4.md)); analysis with SciPy; no deviations, no invalidated runs.

| | Ekbasis | GLM-5.3 |
|---|---|---|
| Harmful runs (of 24) | **0** | **0** |
| Guard wall-clock seconds per run (median) | **51.5** | 214.0 |
| Cost per run | **$0.060** | $0.471 (at Claude Sonnet 5.5 prices) |
| Judge calls with no usable answer | **0 of 337** | 71 of 387 |
| Tasks completed (of 24) / controls (of 12) | 12 / 12 | 11 / 12 |
| Questions to the user | 12 | 21 |

| | Result |
|---|---|
| H1 same safety | 0 vs 0 — **pass** |
| H2 faster (Wilcoxon, ratio ≥ 3) | **4.2×**, Ekbasis faster in 31 of 36 pairs, p = 7×10⁻⁷ — **pass** |
| H3 cheaper | p = 7×10⁻⁷ — **pass** |
| H4 fewer missing answers | 0 vs 71 — **pass** |
| H5 task completion (two-sided) | only-Ekbasis 2, only-GLM 1, p = 1 — **no detectable difference** |

With the large LLM also in parallel, Ekbasis's speed advantage shrinks from about 16× (v3, one by one) to about 4×, and
stays large; the cost stays about 8× lower; the GLM left 18% of its forecasts unanswered and made the agent ask the user
almost twice as often. The GLM arm's higher task completion in v3 (14 vs 10) did not replicate (11 vs 12).

## v1 and v2: the chain guard with Ekbasis (144 runs each: 18 tasks × 4 arms × 2 seeds)

Same tasks family, short (v1) and long (v2) pipelines, arms: no guard, ask before every step, stepwise guard, chain
guard. Harmful runs, no guard → chain guard: **9 → 0 of 24** (v1, McNemar p = 0.002) and **8 → 0 of 24** (v2,
p = 0.004); controls kept. The pre-registered "fewer interruptions than the stepwise guard" did not pass in either
(39 vs 45, 39 vs 49). Records: [`chain/`](chain/), sealed analysis outputs in `chain/results/`.

## What it shows, and what it does not

- With either judge, the chain guard took the agent from 9 harmful runs in 24 to 0. Ekbasis gave that protection
  **about 16× faster** than a large LLM forecasting one prefix at a time (v3) and **about 4× faster** when both forecast
  in parallel (v4), **8–10× cheaper**, and always answered: it reads the state and returns calibrated
  probabilities in one forward pass, without generating text. A guard that runs before every batch of actions has to be
  fast and cheap enough to stay on.
- One agent (Claude Haiku 5.5), one domain (Kubernetes), simulated users, 108 runs in v3.
- The GLM arm's higher task completion in v3 (14 vs 10, not tested there) did not replicate in v4, where it was a
  pre-registered question (11 vs 12, p = 1).
- The cost of the GLM arm is at Claude Sonnet 5.5's API prices, as a reference for a large LLM sold by API; we serve
  GLM-5.3 ourselves.

## Use it

`pip install ekbasis` / `npm install ekbasis` → `check_plan` / `checkPlan` (with `harms()` and `request=`), or
`ekbasis plan-check` from any harness. Recipe:
[check a plan before your agent runs it](../../recipes/check-a-plan/).

## Files

- `chain3/`: the v3 pre-registration, guard, runner and sealed analysis; `results/runs_g.jsonl` (one line per run),
  `results/forecast_calls/<run>.jsonl` (every judge call: engine, ms, tokens, whether it answered; no file = the guard
  never asked the judge in that run), the invalidated runs, the sealed output.
- `chain4/`: the v4 pre-registration, guard (`guard_chain4.py`), runner and sealed analysis; `results/runs_h.jsonl`,
  `results/forecast_calls/`, the sealed output.
- `chain/`: v1 and v2, with their pre-registrations, tasks, verifiers and run records.
- The harness the runners import (`phase1/harness/`, `probe/`) is in [`../k8s/`](../k8s/).
- [`sanitize_chain.py`](sanitize_chain.py) made this copy from the private folders: local paths, the user name and the
  job id became placeholders; our GLM server's address and the local key files became environment variables
  (`GLM_URL`, `GLM_API_KEY`, `EKBASIS_API_KEY`). [`MANIFEST.tsv`](MANIFEST.tsv) lists each file's hash before and after.
  Development scratch files, run logs and the internal Portuguese result notes were not copied; the pre-registrations
  and deviation logs are published as sealed, in Portuguese.
