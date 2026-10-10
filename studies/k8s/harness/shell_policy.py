#!/usr/bin/env python3
"""WS-K8S: PreToolUse hook for the kubectl agent (Bash only). Deny by default: every simple command in the line must
start with an allowed program (kubectl and read-only text tools); no output redirection to files, no subshell tricks
that hide a program. Logs every Bash command with the decision to $K8S_CMDLOG (JSON lines).
Reads the hook JSON on stdin; prints a PreToolUse decision on stdout."""
import json
import os
import re
import shlex
import sys
import time

ALLOWED = {"kubectl", "grep", "egrep", "jq", "head", "tail", "sort", "uniq", "wc", "sleep", "cat", "echo", "printf",
           "ls", "cut", "tr", "column", "true", "false", "base64", "date", "test", "[", "read"}
KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "{", "}"}  # the program is the next word
ENDS = {"done", "fi", "esac", "}"}
SAFE_REDIRECT = re.compile(r"(\d?>&\d|\d?>\s*/dev/null|&>\s*/dev/null)")


def split_simple(cmd):
    """Simple commands of a shell line: split on |, ||, &&, ;, newlines, $( and backticks (contents checked too)."""
    s = cmd.replace("$(", "\n").replace("`", "\n").replace(")", "\n")
    parts = re.split(r"\|\||&&|\||;|\n|&(?!>)", s)
    return [p.strip() for p in parts if p.strip()]


def first_word(part):
    try:
        t = shlex.split(part, posix=True)
    except ValueError:
        t = part.split()
    while t and (t[0] in KEYWORDS or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", t[0])):  # keywords, VAR=value prefixes
        t = t[1:]
    if not t or t[0] in ENDS:
        return ""
    if t[0] == "for":  # a word list, not a command (substitutions in it are checked as their own parts)
        return ""
    return os.path.basename(t[0])


def decide(cmd):
    heredoc_free = re.sub(r"<<-?\s*'?\"?(\w+)'?\"?.*?\n.*?\n\1\b", "", cmd, flags=re.S)  # heredoc bodies are data
    redir = re.sub(SAFE_REDIRECT, "", heredoc_free)
    if re.search(r"(^|[^<>&\d])>{1,2}\s*[^&\s]", redir) or re.search(r"\btee\b", redir):
        return "deny", "Writing files is not available in this environment; pass manifests to kubectl on stdin (kubectl apply -f - <<EOF ... EOF)."
    bad = sorted({first_word(p) for p in split_simple(re.sub(SAFE_REDIRECT, " ", heredoc_free))} - ALLOWED - {""})
    if bad:
        return "deny", (f"Not available in this environment: {', '.join(bad)}. You can use kubectl and read-only text "
                        f"tools ({', '.join(sorted(ALLOWED - {'read', 'true', 'false', '['}))}).")
    return "allow", ""


def main():
    ev = json.load(sys.stdin)
    cmd = (ev.get("tool_input") or {}).get("command", "")
    if ev.get("tool_name") != "Bash":
        dec, why = "deny", "Only the Bash tool is available."
    else:
        dec, why = decide(cmd)
    log = os.environ.get("K8S_CMDLOG")
    if log:
        with open(log, "a") as f:
            f.write(json.dumps({"t": time.time(), "command": cmd, "decision": dec, "reason": why}) + "\n")
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": dec}}
    if why:
        out["hookSpecificOutput"]["permissionDecisionReason"] = why
    print(json.dumps(out))


if __name__ == "__main__":
    main()
