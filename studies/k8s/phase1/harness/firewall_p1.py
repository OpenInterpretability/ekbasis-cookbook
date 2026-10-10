"""WS-K8S Phase 1: add the hashes of the 24 Phase 1 tasks (setup objects, files, request, paths, intent script) to
mission/K8S/firewall_sha256.txt (replacing an earlier Phase 1 block if present)."""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tasks"))
import k8s_tasks as T  # noqa: E402

FW = os.path.abspath(os.path.join(HERE, "..", "..", "firewall_sha256.txt"))
MARK = "# --- Phase 1 tasks"
lines = [l.rstrip("\n") for l in open(FW)] if os.path.exists(FW) else []
if MARK in "\n".join(lines):
    lines = lines[:next(i for i, l in enumerate(lines) if l.startswith(MARK))]
lines.append(f"{MARK} (sha256 of canonical JSON of each task record: setup, files, request, watched, paths, intent)")
for r in T.records():
    h = hashlib.sha256(json.dumps(r, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    lines.append(f"{h}  phase1-task {r['id']}")
open(FW, "w").write("\n".join(lines) + "\n")
print(len(T.TASKS), "Phase 1 task hashes ->", FW)
