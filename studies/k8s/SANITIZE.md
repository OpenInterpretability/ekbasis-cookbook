# What was changed in this copy

This folder is a sanitized copy of the private study folder of the Kubernetes study. The report is
[`PUBLIC_REPORT.md`](PUBLIC_REPORT.md). The copy was made by [`sanitize.py`](sanitize.py) and nothing was edited by hand.
The private originals were not modified.

## What was copied

The files listed in `FILES` in `sanitize.py`, 1,286 in all:
- **Pre-registration and records:** `SPEC_agents.md`, `SPEC_probe.md`, `FROZEN.sha256`, `DEVIATIONS.md`,
  `firewall_sha256.txt`, `spend.jsonl`, `kind-config.yaml`.
- **Tasks, judges and user scripts:** `phase1/tasks/`.
- **Guard and harness:** `phase1/harness/`, `harness/shell_policy.py`, `probe/*.py`, and the pilot scripts.
- **Run records:**
  - `phase1/results/runs_{h,s,p}.jsonl`, `summary*.json`, `extra_stats.json`;
  - the 1,203 per-run files in `phase1/results/sessions/`: the agent transcript, the guard log, the command log, the
    guard config and stderr;
  - the Phase 0 data in `probe/data/` and `pilot/results/pilot_runs.jsonl`.
- **Scripts that recompute every number and their outputs:** `recompute_public.py`, `firewall_lineage_check.py`,
  `cost_ekbasis_tokens.py`, `ekbasis_review.py`.

**Not copied:** internal handoff and status notes, run logs, the Phase 0 pilot transcripts, and the internal pt-BR
result notes. Everything in the report is recomputed from the files above.

## What was changed

1. **Text replacements, in every file, in this order:**

   | What | Replaced by |
   |---|---|
   | the job folder under the user's home | `<job>` |
   | Claude Code project folders | `<claude-projects-dir>` |
   | the study folder's absolute path | `<study>` |
   | other absolute paths on the local disk | `<local-path>` |
   | the user's home | `<home>` |
   | the user name | `<user>` |
   | the job id | `<jobid>` |
   | temporary folders | `<tmp>` |
   | the Ekbasis server's host name | `mac-host` |
   | "Caio's second Mac" (in the SPEC) | "an Apple-silicon Mac" |

2. **Agent transcripts (`*.agent.jsonl`), as JSON:**
   - **The `system/init` event** keeps only `type`, `subtype`, `cwd` (made relative by rule 1), `tools`,
     `mcp_servers`, `model`, `permissionMode`, `claude_code_version` and `output_style`. Removed:
     - the lists of installed plugins, skills, slash commands and agents;
     - the capabilities;
     - the memory and messaging-socket paths;
     - the API-key source, the analytics flags and the view settings.
   - **Every event** loses `session_id`, `uuid`, `request_id`, `rate_limit_info` and the fast-mode fields.
   - **`rate_limit_event` events** (account usage windows) are dropped.
   - **Kept:** everything about the run itself — the agent's messages, tool calls, tool results, denials, the costs and
     usage per turn, and the results.

3. **The two scripts that call the hosted Ekbasis API** (`ekbasis_review.py`, `cost_ekbasis_tokens.py`) read the key
   from the `EKBASIS_API_KEY` environment variable, not from a local file. No key was ever stored in any file.

4. **The harness's fallback path** for a local client install was renamed. If the `ekbasis` client is not installed
   with pip, it is looked for under `$CLAUDE_JOB_DIR/tmp/ekbasis_venv`.

**Not changed:** no number, verdict, task, judge, user script or guard logic. IP addresses in the transcripts are the
kind cluster's internal addresses (172.25.x, 10.96.x, 10.244.x) and were left as they are.

## How to check

- **`MANIFEST.tsv`** lists, for every file:
  - the sha256 of the private original, which is the hash in `FROZEN.sha256` where that file was frozen;
  - the sha256 of this copy;
  - whether the two differ. 540 of the 1,286 files differ.
- **Recompute.** `recompute_public.py` run on this copy gives exactly the same results as on the originals:
  - every per-arm rate, hypothesis, CI, secondary contrast and spend figure is identical;
  - see `recompute_public_output.json` (originals) and `recompute_public_output_sanitized_copy.json` (this copy).
- **Frozen hashes.** On this copy, the `matches_a_frozen_hash` check fails for the files that were sanitized:
  - `runs_h.jsonl` and `runs_s.jsonl`;
  - `guard_lib.py` and `run_agent.py`;
  - `SPEC_agents.md`;
  - the session files.

  For those, use `MANIFEST.tsv` to see that the original's hash is the frozen one.
- **Leak check** (`grep -ri`) over this folder for the user name, the host name, home and job paths, `session_id`,
  `memory_paths`, `messaging_socket`, tokens and keys. The only hits are code, not data:
  - the field names that `sanitize.py` removes, and its own replacement patterns;
  - the `Bearer` header built from the environment variable;
  - the `EKBASIS_API_KEY` variable name;
  - innocent substrings: `task-specific`, `EKB_URL`/`EKB_LOCK`, and a JSON-patch path `/spec/template/spec/volumes/…`.
