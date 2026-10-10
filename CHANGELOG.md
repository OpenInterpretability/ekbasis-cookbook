# Changelog

## Unreleased — 2026-10-10

- Agent study: the same 47 tasks run three times (two runs through the hosted API): harmful runs 23, 24, 26 → 3, 0, 0
  of 47 (average −49.6 pp, 95% CI [37.6, 61.7], bootstrap over tasks); task success roughly doubled. Data and recompute script in
  `studies/agents-3reps/`. The earlier "seed" label meant nothing was seeded: these are repetitions.
- Kubernetes study (pre-registered, run 2026-10-07): kubectl agents on a real kind cluster with and without the Ekbasis
  guard. Haiku harm 66.7% → 5.6% (K-H1 pass), 0.77 vs 2.31 questions per run against asking always (K-H3 pass),
  non-inferiority to a Sonnet-as-forecaster guard failed (K-H2). Report in `docs/K8S_STUDY.md`; sanitized data,
  per-run transcripts, harness and recompute scripts in `studies/k8s/` (`SANITIZE.md` lists every change).

## 0.1.0 — 2026-10-09

First release: the measured use-case map for Ekbasis as a guard and foresee API.

- Guard battery: classic losses 8/8 @ 98–99%, safe commands 0 false alarms, real stash semantics, hook rule layer catches committed-work loss
- Intensive suite: 85 scenarios, 11 domains — 100% on scored cases, honest confidence on ambiguous states
- API tests: choice/noul/score, batching, sessions, INT4↔MLX parity 0.2pp
- Docs: GPU setup incl. the 3 co-tenancy flags, Mac MLX setup, API reference
- Skills: `ekbasis-guard` (when and how to consult before destructive actions)
- Hooks: Claude Code `PreToolUse` example with measured behavior
- Known gaps documented: `push --force` remote loss, prototype shell-check, 32k context cap
