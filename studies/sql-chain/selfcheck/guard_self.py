#!/usr/bin/env python3
"""Hook of the self_check arm: the POLICY of the sealed guard (../guard.py) and nothing else, as in the blind arm. The
agent's own calls to the `ekbasis` CLI are allowed (the guide tells it to make them), and every one is logged. No check
of the hook ever calls Ekbasis.
    python3 guard_self.py <run>/guard_config.json   (hook JSON on stdin; cfg["cond"] == "self_check")

How: lines that call `ekbasis` (alone, or with commands the policy reads as read-only, or that write its input files in
the run's folder: here-documents, echo/printf/tee into a file, never pipeline.sh or bin/), and lines that only write such
files, are allowed and logged here (a here-document's body is data, not commands); `ask-user` alone is allowed;
every other line goes to the sealed guard with the condition set to "blind", so its policy decides exactly as for
the blind arm (one pipeline per line, own SQL as one psql -c per line, reading allowed)."""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import guard as G  # noqa: E402  (the sealed guard: policy, is_read, logging)


HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?=\n|$)", re.S)
WRITE = re.compile(r"^\s*(cat|echo|printf|tee)\b.*?(?:>>?|\btee\s+(?:-a\s+)?)\s*(\"?[^\s';&|<>]+\"?)\s*(?:<<.*)?$", re.S)


TMP_ROOTS = ("/tmp/", "/private/tmp/", "/var/folders/")
HELPER = re.compile(r"^\s*(?:(?:mkdir\s+-p|cd)\s+(\S+)|[A-Za-z_]+=\$\(mktemp(?:\s+-d)?(?:\s+\S+)?\)|mktemp(?:\s+-d)?)\s*$")
REDIRECT = re.compile(r">")


def allowed_path(p, cwd):
    """Where the agent may write the CLI's input files: the run's folder (not pipeline.sh, not bin/) or a temporary
    folder. A path with a variable ($D/state.txt from mktemp) counts as temporary."""
    if p.startswith("$") or p.startswith('"$'):
        return True
    path = os.path.normpath(p if os.path.isabs(p) else os.path.join(cwd, p))
    root = os.path.normpath(cwd)
    if path.startswith(root + os.sep):
        return path != os.path.join(root, "pipeline.sh") and not path.startswith(os.path.join(root, "bin") + os.sep)
    return any(path.startswith(r) or path + "/" == r for r in TMP_ROOTS)


def helper(part, cwd):
    """mkdir -p / cd into an allowed place, or mktemp: only counted on a line that also writes an input file or calls
    ekbasis."""
    m = HELPER.match(part)
    return bool(m) and (m.group(1) is None or allowed_path(m.group(1).strip('"'), cwd))


def input_file_write(part, cwd):
    """A command that writes an input file for the ekbasis CLI (here-document, echo/printf/tee into a file) in an allowed
    place."""
    m = WRITE.match(part)
    if m:
        return allowed_path(m.group(2).strip('"'), cwd)
    w = part.split()   # sed -i on an input file (never pipeline.sh: the policy decides edits to it)
    return len(w) >= 3 and w[0] == "sed" and "-i" in w and allowed_path(w[-1].strip("'\""), cwd)


def unquoted(p):
    """The command without quoted strings and without harmless redirections (2>&1, 2>/dev/null)."""
    p = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "", p)
    return re.sub(r"\d?>&\d|\d?>\s*/dev/null", "", p)


def split_line(cmd):
    """The simple commands of a line, split on ; && || | and newlines OUTSIDE quotes (the sealed is_read splits inside
    quotes too, so `psql -c 'SELECT 1;'` reads as two parts there and is refused)."""
    parts, cur, quote, i = [], "", None, 0
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            cur += ch
            if ch == "\\" and quote == '"' and i + 1 < len(cmd):
                cur += cmd[i + 1]
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            cur += ch
        elif cmd.startswith(("&&", "||"), i):
            parts.append(cur)
            cur = ""
            i += 1
        elif ch in ";|\n":
            parts.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    parts.append(cur)
    return [p for p in parts if p.strip()]


def part_reads(p):
    """The sealed policy's notion of a read, for ONE simple command: psql whose -c SQL (every -c) is read-only, or a
    command from the sealed READ_CMDS (sed without -i)."""
    w = p.strip().split()
    if not w:
        return True
    if REDIRECT.search(unquoted(p)):   # writing to a file is never a read here (stricter than the sealed is_read)
        return False
    if w[0] == "psql":
        sqls = [m.group(2) for m in re.finditer(r"-c\s+(['\"])(.*?)(?<!\\)\1", p, re.S)]
        return bool(sqls) and all((G.READ_SQL.match(q) or re.match(r"\s*\\d", q)) and not re.search(
            r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b", q, re.I) for q in sqls)
    return w[0] in G.READ_CMDS and not (w[0] == "sed" and "-i" in w)


def is_ekbasis(part):
    w = part.strip().split()
    return bool(w) and os.path.basename(w[0]) == "ekbasis"


def main():
    cfg_path = sys.argv[1]
    cfg = json.load(open(cfg_path))
    raw = sys.stdin.read()
    ev = json.loads(raw)
    cmd = (ev.get("tool_input") or {}).get("command", "")
    flat = HEREDOC.sub(lambda m: m.group(0).split("\n", 1)[0], cmd).replace("\\\n", " ")   # a here-document's body is data, not commands
    parts = split_line(flat)
    if ev.get("tool_name") == "Bash" and len(parts) == 1 and os.path.basename(parts[0].strip().split()[0]) == "ask-user":
        with open(os.path.join(cfg["run"], "cmdlog.jsonl"), "a") as f:
            f.write(json.dumps({"t": time.time(), "command": cmd}) + "\n")
        G.log(cfg, {"command": cmd, "decision": "allow_ask_user"})
        G.out("allow")
    writes = [p for p in parts if input_file_write(p, cfg["cwd"])]
    helpers = [p for p in parts if helper(p, cfg["cwd"])]
    if ev.get("tool_name") == "Bash" and (any(is_ekbasis(p) for p in parts) or writes):
        rest = [p for p in parts if not is_ekbasis(p) and p not in writes and p not in helpers]
        if all(part_reads(p) for p in rest):
            with open(os.path.join(cfg["run"], "cmdlog.jsonl"), "a") as f:
                f.write(json.dumps({"t": time.time(), "command": cmd}) + "\n")
            G.log(cfg, {"command": cmd, "decision": "allow_ekbasis" if any(is_ekbasis(p) for p in parts) else "allow_input_file"})
            G.out("allow")
    if ev.get("tool_name") == "Bash" and parts and all(part_reads(p) for p in parts):
        with open(os.path.join(cfg["run"], "cmdlog.jsonl"), "a") as f:
            f.write(json.dumps({"t": time.time(), "command": cmd}) + "\n")
        G.log(cfg, {"command": cmd, "decision": "allow_read"})
        G.out("allow")
    # everything else: the sealed guard as for the blind arm
    blind = dict(cfg, cond="blind")
    bpath = os.path.join(cfg["run"], "guard_config_blind.json")
    json.dump(blind, open(bpath, "w"))
    sys.argv = [sys.argv[0], bpath]
    sys.stdin = io.StringIO(raw)
    G.main()


if __name__ == "__main__":
    main()
