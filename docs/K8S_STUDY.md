# Kubernetes study: kubectl agents with an Ekbasis guard on a real cluster

A pre-registered study, run on 2026-10-07 on a real kind cluster (Kubernetes v1.37.0, 3 nodes). It is a follow-up to
[When Does a Consequence Model Make AI Agents Safer?](https://doi.org/10.5281/zenodo.23197341) in a new domain.

The full report, with the timeline, every table, the deviations and the contamination check, is
[`studies/k8s/PUBLIC_REPORT.md`](../studies/k8s/PUBLIC_REPORT.md). The run records, the per-run transcripts and the
scripts that recompute every number are in [`studies/k8s/`](../studies/k8s/): a sanitized copy, see
[`SANITIZE.md`](../studies/k8s/SANITIZE.md). `python3 recompute_public.py` reproduces every number without a cluster.

## What was tested

- **Agent.** Claude Haiku 4.5 (thinking off, 2 seeds), plus Claude Sonnet 5.5 as a secondary agent (1 seed). Both drive
  `kubectl` through Bash.
- **Tasks.** 24 fresh tasks:
  - 18 with a hidden harm: data loss, a Service outage, a broken next restart, or another team's object deleted;
  - 6 controls.

  In 6 of the harm tasks, the request itself names the harmful action.
- **Conditions,** checked before each mutating command:

  | Condition | What happens |
  |---|---|
  | `blind` | nothing |
  | `ask_ekbasis` | a guard: code checks for three comparisons, Ekbasis-27B forecasts 11 consequence and intent questions, a safer way that Ekbasis checked is offered, and otherwise the user is asked |
  | `ask_sonnet` | the same guard, with Claude Sonnet 5.5 as the forecaster |
  | `ask_always` | the user is asked every time, with no forecast |

- **The user.** A frozen regex script that reads the facts shown with each question. The answer arrives as the next user
  message.
- **Ekbasis.** The public `Ekbasis-27B-MLX-4bit` build, served on one Apple-silicon Mac.

## Results (Haiku, 36 harm-task runs per condition)

| | blind | ask_ekbasis | ask_sonnet | ask_always |
|---|---|---|---|---|
| harmful runs | 24/36 (**66.7%**) | 2/36 (**5.6%**) | 1/36 (2.8%) | 0/36 (0%) |
| success (goal met, no harm) | 30.6% | 83.3% | 88.9% | 83.3% |
| controls done | 12/12 | 12/12 | 12/12 | 12/12 |
| questions to the user per run | — | **0.77** | 0.60 | 2.31 |

**Pre-registered hypotheses.** Paired bootstrap over tasks, 95% CI.

| | criterion | result | verdict |
|---|---|---|---|
| K-H1 | Ekbasis guard vs blind: harm cut ≥ 50%, CI < 0, success not worse, controls ≥ 90% | −61.1 pts [−80.6, −38.9] | **PASS** |
| K-H2 | Ekbasis guard vs Sonnet guard: harm CI upper bound < +8 pts | +2.8 pts [−5.6, **+11.1**] | **FAIL** |
| K-H3 | Ekbasis guard vs ask_always: fewer questions, CI < 0 | −1.54 [−2.04, −1.06] (33% as many) | **PASS** |

**Sonnet as the agent (secondary, 1 seed).** Harmful runs went from 6/18 blind to 0/18 with the Ekbasis guard (−33.3
pts [−55.6, −11.1]).

## How to read it

- **The safety gain is not over asking every time.** With this simulated user, asking before every command also
  avoided all harm. The measured benefit of the forecaster is **asking a third as often**.
- **Ekbasis was not shown non-inferior to Sonnet as the forecaster** (K-H2 failed). With harm near zero in both arms, one
  run moves the difference by 2.8 points.
- **The 3 harms under a guard came from the user script.** In each, the guard flagged the consequence and asked, and the
  script approved a command form its regex did not recognise. They count as harm.
- **The result is for the whole guard, not Ekbasis alone.** The guard is Ekbasis plus code checks plus a hand-written
  safer-way catalog. The task families were the ones where Ekbasis did well in an earlier probe on the same cluster. In
  that probe, its pre-registered go/no-go rule had said NO-GO: 3 confident errors against a limit of 2. The code checks
  cover exactly those errors.
- **Latency.** On the MLX 4-bit build on one shared Mac, the median was 29.9 s per forecaster request, against 4.7 s for
  Sonnet through the API. This study did not measure a GPU server.
- **Cost and data.**
  - The Sonnet forecaster cost **US$0.073 per run**, 4× the Haiku agent itself, and sends the cluster state to an external
    API.
  - The Ekbasis guard has no per-call API cost and keeps the state on your network; the hardware that serves it is not
    priced here.
- **Contamination.** We compared the 495 evaluation texts with the 230,625 rows of the published training lineage
  (`ekbasis-data`, `eikos-decisions`): 0 exact matches and 0 shared 13-grams. All items were written three days after the
  model's release. Withheld replay rows and the base model's pretraining could not be checked.
- **Scope.** One kind cluster on one Mac, our own tasks and user scripts, and two seeds. The real-user test is still to
  be done.

## Cost

*Descriptive, not pre-registered.* This prices the Ekbasis guard's actual requests at the hosted API's list price,
US$0.04 per 1M input tokens with no output charge, next to what the Sonnet guard actually cost.

**How the tokens were counted.** The backend counts the state once per question, and the guard asks 11–12 questions per
request. The question tokens are exact. The state tokens are estimated from the logged state length; replaying 10
byte-identical requests checked the estimate to within 1% on average.

| Haiku runs | Input tokens per run (median / mean) | US$ per run | Harmful runs |
|---|---|---|---|
| Ekbasis guard, at the hosted price | 56,941 / 65,991 | **0.0026** (mean; median 0.0023) | 2/36 |
| Sonnet guard, as paid via `claude -p` | — | 0.073 (mean) | 1/36 |

- **Cost ratio.** The Sonnet guard cost **27.5×** as much per run.
- **Harm.** The two guards' harm did not differ significantly, but Ekbasis was not shown non-inferior (K-H2 failed).
- **Caveats.**
  - The Sonnet figure includes the CLI's prompt overhead.
  - The Ekbasis figure is a list price applied to the requests, not a measured bill. The study itself ran Ekbasis on a
    local Mac.

## Using the same guard pattern

This study's guard is a Claude Code `PreToolUse` hook that:
- denies a mutating `kubectl` call;
- returns either a checked safer way or "the user has been asked";
- delivers the user's answer as the next user message.

The git hook in [`hooks/`](../hooks/) is also a `PreToolUse` hook, but it asks through Claude Code's own confirmation;
the study's guard code is in [`studies/k8s/phase1/harness/`](../studies/k8s/phase1/harness/). For Kubernetes, the study's lesson is to keep the deterministic checks
(immutable fields, selector vs labels, quota arithmetic) in code and let the model answer the consequence and intent
questions.
