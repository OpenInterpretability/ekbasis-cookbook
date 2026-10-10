# AGENTS.md

Guidance for AI agents that use Ekbasis or work in this repository.

## Using Ekbasis from an agent

- Reference written for agents (formats, when to consult, decision rules, errors, feedback):
  https://openinterp.org/ekbasis/agents.md
- Installable skill: [`skills/ekbasis-guard/SKILL.md`](skills/ekbasis-guard/SKILL.md)
- Claude Code hook: [`hooks/`](hooks/README.md)
- Hosted API: `EKBASIS_URL=https://openinterp.org/api/v1`, `EKBASIS_API_KEY=ekb_…` (keys at https://openinterp.org/console).
  Self-hosted: point `EKBASIS_URL` at your own server.
- Treat "CANNOT FORESEE" (exit 3, or any 401/402/403/5xx/timeout) as risky. A low probability is not proof of safety.

## Working in this repository

- Every number in the README and docs was measured. Do not add or change a number without the run that produced it
  (scripts and outputs live next to it: `examples/`, `studies/`).
- `studies/k8s/` is a sanitized copy of a pre-registered study; `MANIFEST.tsv` links each file to its frozen original.
  Do not edit those files; rerun `recompute_public.py` to check numbers.
- Run a scenario suite: `EKBASIS_URL=... EKBASIS_API_KEY=... python examples/run_suite.py examples/scenarios_intensive.jsonl`
  (about 1.5k input tokens per scenario on the hosted API).
- Never commit keys, local paths or machine names; `studies/k8s/sanitize.py` shows what to strip from agent transcripts.
- User-facing wording: Ekbasis *foresees*; it does not judge. Use "cannot foresee", not "cannot judge".
