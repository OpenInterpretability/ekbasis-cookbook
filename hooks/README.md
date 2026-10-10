# Claude Code hook: the guard as automatic confirmation

The `ekbasis-claude-hook` binary (installed with the [client](https://github.com/OpenInterpretability/ekbasis)) intercepts every `Bash` tool call in Claude Code and consults the consequence model **before** the command runs.

## Install (per machine)

```bash
pip install ekbasis
export EKBASIS_URL=http://your-server:8010    # put in ~/.zshrc for persistence
```

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "ekbasis-claude-hook", "timeout": 30}]
      }
    ]
  }
}
```

## Environment

| variable | default | meaning |
|---|---|---|
| `EKBASIS_URL` | `http://127.0.0.1:8000` | the Ekbasis API server |
| `EKBASIS_GUARD_MODE` | `ask` | `ask` = Claude asks the human before risky commands; `deny` = the hook blocks them outright |
| `EKBASIS_HOOK_DEADLINE` | `25` | seconds; the hook gives up consulting after this (must stay below the hook `timeout`) |

## What it adds beyond the plain model

The hook runs a **rule layer** on top of the model: it simulates the git refs of the command line and flags **commits that no branch, tag, remote-tracking branch or stash would hold** after it (`branch -D` with unique commits, forced branch moves, `reset --hard <commit>`, tag deletion, `update-ref`). The plain model question covers uncommitted work; the rule covers committed history. Measured: `git branch -D` with a unique commit → the CLI alone passes it, **the hook catches it** ("ask" with the explanation).

## Measured behavior (October 2026)

- `git reset --hard` with uncommitted work → **ask** (model: 99% lose uncommitted work)
- `git status`, `git checkout main` (clean) → silent, no ask
- `git branch -D` with unique commits → **ask** (rule layer)
- `git push --force` against a diverged remote → **not flagged today** (known gap — review force-pushes manually)

## Latency note

With the guard on a GPU (~0.5 s/call) the hook is invisible; on Mac MLX (5–12 s) raise both the deadline and the hook timeout together (`EKBASIS_HOOK_DEADLINE=60`, `"timeout": 90`).
