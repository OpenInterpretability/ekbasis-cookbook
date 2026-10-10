"""Make the public copy of the WS-K8S study from the private study folder. The originals are never modified.

    python3 sanitize.py <private study folder> <output folder>

What it does (SANITIZE.md has the full account):
  - copies only the files listed in FILES (records, tasks, harness, run records, per-run sessions, recompute scripts);
  - in every text file, replaces local paths, the user name, the job id and the Ekbasis host name with placeholders
    (REPLACE, applied in order);
  - in every per-run agent transcript (*.agent.jsonl), keeps the content of the run and removes what identifies the local
    setup or account: the init event keeps only INIT_KEEP; every event loses DROP_KEYS; rate-limit events are dropped;
  - in the two scripts that call the hosted Ekbasis API, reads the key from the EKBASIS_API_KEY environment variable
    instead of a local file;
  - writes MANIFEST.tsv: for each published file, the sha256 of the original (as in FROZEN.sha256) and of the copy."""
import glob
import hashlib
import json
import os
import re
import shutil
import sys

SRC, DST = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])

FILES = [
    "PUBLIC_REPORT.md", "SPEC_agents.md", "SPEC_probe.md", "FROZEN.sha256", "DEVIATIONS.md", "firewall_sha256.txt",
    "spend.jsonl", "kind-config.yaml",
    "recompute_public.py", "recompute_public_output.json", "firewall_lineage_check.py", "firewall_lineage_check.json",
    "cost_ekbasis_tokens.py", "cost_ekbasis_tokens_output.json", "ekbasis_review.py", "ekbasis_review_output.json",
    "ekbasis_review_output_round1.json",
    "harness/shell_policy.py",
    "probe/*.py", "probe/cluster_info.json", "probe/data/*",
    "pilot/pilot_tasks.py", "pilot/run_pilot.py", "pilot/results/pilot_runs.jsonl",
    "phase1/tasks/k8s_tasks.py", "phase1/tasks/verify/*.json",
    "phase1/harness/*.py",
    "phase1/results/runs_h.jsonl", "phase1/results/runs_s.jsonl", "phase1/results/runs_p.jsonl",
    "phase1/results/summary.json", "phase1/results/summary_print.json", "phase1/results/extra_stats.json",
    "phase1/results/sessions/*",
]

USER = "caio" + "vicentino"  # literals are split so this file does not match the leak check it is part of
JOB = "943" + "32945"
HOME_ROOT = "/" + "Users/"
JOBS_DIR = "claude" + "/jobs/"
VOL = "/" + "Volumes/SSD Major"
HOST = "Mac" + "Book-Pro-4"
REPLACE = [
    (re.compile(HOME_ROOT + USER + r"/\." + JOBS_DIR + JOB), "<job>"),
    (re.compile(HOME_ROOT + USER + r"/\.claude/projects/[^\s\"'\\]*"), "<claude-projects-dir>"),
    (re.compile(VOL + "/news/decision_model/mission/K8S"), "<study>"),
    (re.compile(VOL + r"[^\s\"'\\]*"), "<local-path>"),
    (re.compile(HOME_ROOT + USER), "<home>"),
    (re.compile(r"-Users-" + USER + r"[A-Za-z0-9_-]*"), "<claude-projects-dir>"),
    (re.compile(USER), "<user>"),
    (re.compile(JOB), "<jobid>"),
    (re.compile(r"Caio's second Mac"), "an Apple-silicon Mac"),
    (re.compile(HOST + r"\.local"), "mac-host"),
    (re.compile(r"/private/tmp/claude-[0-9]+/[^\s\"'\\]*"), "<tmp>"),
]
# the scripts that call the hosted API: key from the environment, never from a local file
KEY_FILE_READ = 'open(os.path.expanduser("~/.config/ekbasis/' + 'ekb' + '_api' + '_key")).read().strip()'
KEY_FILE_DOC = "~/.config/ekbasis/" + "ekb" + "_api" + "_key"
CODE_FIXES = [(KEY_FILE_READ, 'os.environ["EKBASIS_API_KEY"]'), (KEY_FILE_DOC, "the EKBASIS_API_KEY environment variable"),
              ('"ekb' + '_venv"', '"ekbasis_venv"')]

INIT_KEEP = {"type", "subtype", "cwd", "tools", "mcp_servers", "model", "permissionMode", "claude_code_version", "output_style"}
DROP_KEYS = {"session_id", "uuid", "request_id", "rate_limit_info", "fast_mode_state", "fast_mode_disabled_reason",
             "apiKeySource", "memory_paths", "messaging_socket_path", "slash_commands", "terminal_slash_commands", "skills",
             "plugins", "agents", "capabilities", "analytics_disabled", "product_feedback_disabled", "per_turn_effort_active",
             "view_mode"}


def text_clean(t):
    for pat, rep in REPLACE:
        t = pat.sub(rep, t)
    for a, b in CODE_FIXES:
        t = t.replace(a, b)
    return t


def agent_clean(t):
    out = []
    for line in t.splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("type") == "rate_limit_event":
            continue
        if d.get("type") == "system" and d.get("subtype") == "init":
            d = {k: v for k, v in d.items() if k in INIT_KEEP}
        else:
            d = {k: v for k, v in d.items() if k not in DROP_KEYS}
        out.append(json.dumps(d, ensure_ascii=False))
    return text_clean("\n".join(out) + "\n")


def sha(b):
    return hashlib.sha256(b).hexdigest()


paths = []
for pat in FILES:
    hits = sorted(glob.glob(os.path.join(SRC, pat)))
    if not hits:
        sys.exit(f"missing: {pat}")
    paths += [p for p in hits if os.path.isfile(p) and "__pycache__" not in p]
manifest = ["# path\tsha256 of the private original\tsha256 of this copy\tchanged"]
stats = {"files": 0, "changed": 0, "agent_transcripts": 0}
for p in paths:
    rel = os.path.relpath(p, SRC)
    raw = open(p, "rb").read()
    t = raw.decode("utf-8")
    new = agent_clean(t) if rel.endswith(".agent.jsonl") else text_clean(t)
    stats["agent_transcripts"] += rel.endswith(".agent.jsonl")
    out = os.path.join(DST, rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(new)
    nb = new.encode("utf-8")
    changed = nb != raw
    stats["files"] += 1
    stats["changed"] += changed
    manifest.append(f"{rel}\t{sha(raw)}\t{sha(nb)}\t{'yes' if changed else 'no'}")
open(os.path.join(DST, "MANIFEST.tsv"), "w").write("\n".join(manifest) + "\n")
print(json.dumps(stats))
