# Changelog

## 0.1.0 — 2026-10-09

First release: the measured use-case map for Ekbasis as a guard and foresee API.

- Guard battery: classic losses 8/8 @ 98–99%, safe commands 0 false alarms, real stash semantics, hook rule layer catches committed-work loss
- Intensive suite: 85 scenarios, 11 domains — 100% on scored cases, honest confidence on ambiguous states
- API tests: choice/noul/score, batching, sessions, INT4↔MLX parity 0.2pp
- Docs: GPU setup incl. the 3 co-tenancy flags, Mac MLX setup, API reference
- Skills: `ekbasis-guard` (when and how to consult before destructive actions)
- Hooks: Claude Code `PreToolUse` example with measured behavior
- Known gaps documented: `push --force` remote loss, prototype shell-check, 32k context cap
