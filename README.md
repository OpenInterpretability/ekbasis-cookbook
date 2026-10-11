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

## More studies (10–11 October 2026), negative results included

| study | result | where |
|---|---|---|
| Migration guard vs real public incidents (34 candidates mined from 16 repos; not pre-registered) | of 25 confirmed in-scope incidents, **9 flagged for the right reason**, 5 for another reason, 1 spurious, 2 declined, **8 missed** | [studies/migrations-real-incidents/](studies/migrations-real-incidents/) |
| Migration guard for Django and Alembic (pre-registered v4, v5) | v4 **failed** (code migrations counted as risky). v5 (`on-code: warn`): **Alembic passes P1–P4**; Django fails P4 (recall 0.824 < 0.85) and ships as **experimental**. Counting review-by-hand as missed, total recall is 0.48 (Django) and 0.31 (Alembic) | [studies/migrations-frameworks/](studies/migrations-frameworks/) |
| Constraint facts about existing rows in the migration state (pre-registered) | **negative**: P1 gain on 9 new incidents was **0** (3/9 → 3/9; underpowered); false-alarm cost within limits (P3 at the limit). Not shipped | [studies/migrations-constraint-facts/](studies/migrations-constraint-facts/) |
| Terraform/OpenTofu plan guard, 69 local scenarios labelled by execution (pre-registered) | **tie** with a simple rule: composite F1 0.871 vs 0.824, **+0.047 against a +0.05 margin** (McNemar p = 0.45). Parked; no cloud providers tested | [studies/terraform-plan-guard/](studies/terraform-plan-guard/) |
| `intent_check` as a defense on the official AgentDojo (pre-registered, 1,191 runs) | security **inconclusive by floor**: GLM-5.3-Flash with no defense fell for **0/300** attacks. Cost: **−3.1 pp** utility without attack, **−2.3 pp** under attack (within limits). All **6 blocks were false alarms**, 3 of them on explicit delegation ("follow the instructions in the file") | [studies/agentdojo-intent-check/](studies/agentdojo-intent-check/) |
| Migration guard for Rails (pre-registered v6, Mastodon and Maybe) | P1, P3, P4 pass (accuracy 0.886 vs 0.607 for the rules; false alarms 15.2% vs 52.5%; recall 40/41). **P2 fails**: reason right on 33/40 = 0.825, target 0.85. Rails stays **experimental** | [studies/migrations-rails/](studies/migrations-rails/) |
| intent_check on published successful attacks, replayed (pre-registered; held-out on 4 more attack types) | **2,092 of 2,092 real successful attacks stopped** across 5 attack texts and 13 agent setups (3 more were a benchmark artifact: the user's own request gave the attacker's IBAN); false alarms on 1.4–1.7% of benign runs. GPT-4o: published defenses leave 6.8–41.7% of attacks; replayed intent_check ~0.2%. A replay is not a live run | [studies/intent-check-replay/](studies/intent-check-replay/) |
| intent_check vs a large general LLM (GLM-5.3-Flash) as the judge, same state (pre-registered, 500 calls) | **tie at the ceiling**: 250/250 attack calls flagged by both; Ekbasis 0/250 false alarms, the LLM 2/250 (no answers). Ekbasis ~1.4 s, the LLM 3.7 s. What makes these calls easy is the shielded state | [studies/llm-judge-intent/](studies/llm-judge-intent/) |
| Migration guard vs a large general LLM as the judge, same state (pre-registered, 184 v3 migrations) | the LLM is **more accurate with replica statistics** (0.918 vs 0.897; 0.987 vs 0.961 where it answered) and better calibrated; a tie without them (0.880 vs 0.886). Ekbasis 2–2.6 s and always answers; the LLM 14–23 s, no answer on 17–23% | [studies/llm-judge-migrations/](studies/llm-judge-migrations/) |
| Migration guard vs a rule written from the PostgreSQL docs with the same facts (pre-registered; held-out v5/v6 and Rails v7) | **the model does not add accuracy over the facts**: v3 rule 0.913–0.946 vs 0.880; held-out frameworks 0.960 vs 0.945; on 0.1.21 (Rails v7) 0.889 vs 0.896, a tie. The value is the fact pipeline. Shared false alarms come from synthetic seed data | [studies/migrations-rich-rule/](studies/migrations-rich-rule/) |
| Rails v7 (pre-registered; shipped as supported in 0.1.21) | accuracy 0.896 vs 0.730 for regex rules, reason 118/119, false alarms 17.0% vs 44.1%, recall 119/119, no regression on v3 | [studies/migrations-rails-v7/](studies/migrations-rails-v7/) |
| Code probes, edited migrations, setup SQL (pre-registered; shipped in 0.1.20) | no regression on v3 (false alarms 20→20, 19→19; recall 54→54); the gain on new incidents was **not demonstrated** (only 4 found) | [studies/migrations-code-probes/](studies/migrations-code-probes/) |
| Kubernetes guard v2 vs a rich rule with the same facts, 75 scenarios (65 real) (pre-registered) | **the rule is ahead**: composite F1 0.991 vs 0.955; the v1 gain came from the derived facts, not the model | [studies/vertical-kubernetes-v2/](studies/vertical-kubernetes-v2/) |
| Schema cut by a parser in the migration guard (pre-registered, 184 v3 migrations) | **shipped in 0.1.19**: accuracy 0.880 → 0.897 with replica statistics, 0.886 → 0.886 without (non-inferiority on the point estimate; CI −2.7 to +2.7 pp); false alarms 20 → 17 and 19 → 18; median input tokens −23% / −30%. The previous name-match state missed a touched table in 59 of 530 dev migrations | [studies/migrations-schema-cut/](studies/migrations-schema-cut/) |
| Long states: does the guard stay right as the state grows? (pre-registered, 184 migrations padded with real tables) | **no loss up to 64k tokens** (accuracy 0.880 at the native length and at 64k; same AUROC; wherever the deciding tables sit). Only the "fails" calibration gets worse (ECE 0.034 → 0.063). 120k is **exploratory** (65 items, 0 verdicts changed). Cold latency 1.7 s → 24.5 s at 64k | [studies/long-context/](studies/long-context/) |
| `read_once` (all questions in one pass) in the migration guard (pre-registered) | **failed**: −47% tokens and 5.1 → 3.0 s, unchanged with replica statistics, but without them it **missed 2 of 56 risky** migrations (CI crosses −2 pp). Not the default | [studies/read-once/](studies/read-once/) |
| Per-client calibration from feedback (pre-registered, simulated clients) | **failed**: +1.8 pp at k = 20 (CI crosses 0), Brier worse, and 20% adversarial feedback cut recall 0.55 → 0.47. Diagnose instead of auto-tuning | [studies/per-client-calibration/](studies/per-client-calibration/) |
| Hardening `intent_check` (pre-registered; published attacks only) | text aimed at the checker (AgentDojo attacks, the planted line that silenced the generic guard, four AgentWatcher monitor attacks) **did not silence it: 70/70** at every attack (easy items, no attack optimized against it). Explicit delegation improved only in part (false alarms 5 → 4 of 92; criterion failed). Stays a signal to ask a person | [studies/intent-check-hardening/](studies/intent-check-hardening/) |
| Kubernetes guard, 57 scenarios labelled by execution on kind (pre-registered pilot) | **passed**: composite F1 0.937 vs 0.697 for a simple rule (McNemar p = 0.001). **Caveat**: scenarios written by us where the rule is blind; a v2 against a rich rule on real charts is running | [studies/vertical-kubernetes/](studies/vertical-kubernetes/) |
| AWS plans on LocalStack, 55 scenarios (pre-registered pilot) | **tie** on the composite (F1 0.851 vs 0.824), but **data loss clearly better** (F1 0.93 vs 0.67, p = 0.004). Exposure not labelled (LocalStack Community does not enforce IAM) | [studies/vertical-aws-localstack/](studies/vertical-aws-localstack/) |
| dbt on DuckDB, 196 test changes (pre-registered pilot) | only data loss passes against a naive rule; a rule written from the dbt docs **beats it** (F1 0.806 vs 0.675). Not a product on its own | [studies/vertical-dbt/](studies/vertical-dbt/) |
| Will this Dependabot bump break CI? 329 real PRs (pre-registered pilot) | ranks risk (AUROC 0.763; 8 of the top 10 broke) and raises fewer false alarms (9.8% vs 26.8%), but **F1 ties** the one-line rule "major version" (+0.01). Triage, not a gate | [studies/vertical-dependabot/](studies/vertical-dependabot/) |
| SQL that coding agents run, 70 test scenarios on PostgreSQL (pre-registered pilot) | F1 0.805 vs 0.264 for a regex linter; catches 80% of what the linter cannot see (a WHERE wider than asked). **False alarms 27%**, above the 20% limit; the lock question is weak | [studies/vertical-agent-sql/](studies/vertical-agent-sql/) |

Each folder has its plan (when pre-registered), the per-item answers without third-party code, and a recompute script
or the analysis that reproduces the numbers above.

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
