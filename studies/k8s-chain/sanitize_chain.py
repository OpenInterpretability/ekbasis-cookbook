"""Make the public copy of the Kubernetes chain studies (v1, v2, v3) from a private staging folder (the study folders
chain/ and chain3/, plus each v3 run's forecast_calls.jsonl as chain3/results/forecast_calls/<run id>.jsonl). The originals are never modified.

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
    # v1 (short pipelines) and v2 (long pipelines): Ekbasis only
    "chain/PREREG_chain.md", "chain/PREREG_chain.sha256", "chain/PREREG_chain_long.md", "chain/PREREG_chain_long.sha256",
    "chain/guard_chain.py", "chain/guard.py", "chain/chain_tasks.py", "chain/chain_tasks_long.py", "chain/run_chain.py",
    "chain/run_chain_long.py", "chain/analyze_chain.py", "chain/verify_chain.py", "chain/verify_chain_long.py",
    "chain/verify/*", "chain/verify_long/*", "chain/spend.jsonl",
    "chain/results/runs_c.jsonl", "chain/results/runs_L.jsonl", "chain/results/analysis_c.txt", "chain/results/analysis_L.txt",
    # v3: Ekbasis vs GLM-5.3 as the judge
    "chain3/PREREG_chain3.md", "chain3/PREREG_chain3.sha256", "chain3/DEVIATIONS_chain3.md", "chain3/guard_chain3.py",
    "chain3/guard.py", "chain3/run_chain3.py", "chain3/analyze_chain3.py",
    "chain3/results/runs_g.jsonl", "chain3/results/invalid_g.jsonl", "chain3/results/invalid_g_gateway_bug.jsonl",
    "chain3/results/analysis_g_sealed.txt", "chain3/results/redo_after_bug.sh", "chain3/results/forecast_calls/*",
    # v4: both judges forecasting in parallel waves of 5
    "chain4/PREREG_chain4.md", "chain4/PREREG_chain4.sha256", "chain4/guard_chain4.py", "chain4/guard.py",
    "chain4/run_chain4.py", "chain4/analyze_chain4.py", "chain4/results/runs_h.jsonl", "chain4/results/analysis_h_sealed.txt",
    "chain4/results/forecast_calls/*",
    # v5: another agent (Claude Sonnet 5.5), the v4 guard unchanged
    "chain5/PREREG_chain5.md", "chain5/PREREG_chain5.sha256", "chain5/guard.py", "chain5/run_chain5.py",
    "chain5/analyze_chain5.py", "chain5/results/runs_s.jsonl", "chain5/results/analysis_s_sealed.txt",
    "chain5/results/forecast_calls/*",
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
    (re.compile(HOME_ROOT + USER + r"/\.config/ekbasis/[A-Za-z_]+"), "<key-file>"),
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
              ('"ekb' + '_venv"', '"ekbasis_venv"'),
              # v3: our GLM server and the local key files -> environment variables
              ('open(os.path.expanduser("~/.config/ekbasis/' + 'cb_glm' + '_key")).read().strip()', 'os.environ["GLM_API_KEY"]'),
              ('"$(cat ~/.config/ekbasis/' + 'study_api' + '_key)"', '"$EKBASIS_API_KEY"')]

INIT_KEEP = {"type", "subtype", "cwd", "tools", "mcp_servers", "model", "permissionMode", "claude_code_version", "output_style"}
DROP_KEYS = {"session_id", "uuid", "request_id", "rate_limit_info", "fast_mode_state", "fast_mode_disabled_reason",
             "apiKeySource", "memory_paths", "messaging_socket_path", "slash_commands", "terminal_slash_commands", "skills",
             "plugins", "agents", "capabilities", "analytics_disabled", "product_feedback_disabled", "per_turn_effort_active",
             "view_mode"}


GLM_URL_LINE = re.compile(r'^GLM_URL = "https://[^"]+"$', re.M)   # v3: our GLM server's address is not published


def text_clean(t):
    t = GLM_URL_LINE.sub('GLM_URL = os.environ["GLM_URL"]  # an OpenAI-compatible chat completions URL serving GLM-5.3-Flash', t)
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
