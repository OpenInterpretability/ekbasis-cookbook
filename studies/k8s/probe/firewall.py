"""WS-K8S: sha256 of every new evaluation item (Phase 0 scenarios with their pass-A state, pilot tasks), so future
training data (FX/V49+) can be checked against them (exact and near copies).
    python3 firewall.py  -> ../firewall_sha256.txt"""
from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "pilot"))


def h(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def main():
    lines = ["# WS-K8S evaluation items (Phase 0). sha256 of canonical JSON (sort_keys). Scenario items: the template "
             "(objects, command, files) and the rendered pass-A item (command, files, state summary). Prompt texts are "
             "hashed too. Pilot: setup + request template."]
    scen = [json.loads(l) for l in open(os.path.join(HERE, "data", "scenarios.jsonl"))]
    rows = {}
    p = os.path.join(HERE, "data", "truth_A.jsonl")
    if os.path.exists(p):
        rows = {json.loads(l)["id"]: json.loads(l) for l in open(p)}
    for s in scen:
        lines.append(f"{h({k: s[k] for k in ('objects', 'command', 'files')})}  scenario-template {s['id']}")
        r = rows.get(s["id"])
        if r and "summary" in r:
            lines.append(f"{h({'command': r['command'], 'files': r['files'], 'summary': r['summary']})}  scenario-passA {s['id']}")
    ip = os.path.join(HERE, "data", "items.jsonl")
    if os.path.exists(ip):
        for l in open(ip):
            it = json.loads(l)
            body = it.get("prompt") or it.get("state")
            lines.append(f"{hashlib.sha256(body.encode()).hexdigest()}  prompt {it['id']} {it['cond']}")
    import pilot_tasks as PT
    for t in PT.task_records():
        lines.append(f"{h({'setup': t['setup'], 'request': t['request']})}  pilot {t['id']}")
    out = os.path.join(HERE, "..", "firewall_sha256.txt")
    open(out, "w").write("\n".join(lines) + "\n")
    print(len(lines) - 1, "hashes ->", out)


if __name__ == "__main__":
    main()
