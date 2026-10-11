"""Step 3: the label of each sampled PR, from GitHub Actions check runs only (PREREG §3). No model is involved.

broken      some GitHub Actions job fails (failure, timed_out, startup_failure) on the PR's head commit, the same job name
            succeeds on the PR's base commit, and the job is not systematic in that repository.
ok          no GitHub Actions job fails on the head commit, and at least one succeeds.
excluded    no_ci (no completed job with success or failure), pending (a job not completed), human_commits (a commit not
            authored by Dependabot), unattributable (every failing job also fails, or does not exist, on the base), or
            error (GitHub returned an error).
systematic  a job name that fails on at least half of the repository's sampled PRs where it ran, with at least 4 such
            PRs: a Dependabot-wide failure (missing secrets, a broken workflow), not this upgrade. It is ignored.
"""
import json
import os
import re
import sys
from collections import defaultdict

from ghc import ROOT, gh

FAIL = {"failure", "timed_out", "startup_failure"}
# Jobs that are not the build or the tests: bots, review and repository chores (PREREG §3).
META = re.compile(r"dependabot|copilot|auto-?merge|label|triage|welcome|greet|stale|dependency[- ]review|codeql|"
                  r"^analyze|pr[- ]title|semantic|conventional|pullfrog|claude|coderabbit|codecov|"
                  r"coverage[- ]badge|\bcla\b|\bdco\b|\bassign", re.I)
IGNORE = {"skipped", "neutral", "cancelled", "stale", "action_required", None}


def runs(repo, sha):
    out, page = [], 1
    while True:
        d = gh(f"repos/{repo}/commits/{sha}/check-runs?filter=latest&per_page=100&page={page}")
        if not isinstance(d, dict) or "__error__" in d:
            return None
        rs = d.get("check_runs", [])
        out += rs
        if len(rs) < 100 or page >= 5:
            break
        page += 1
    return [r for r in out if (r.get("app") or {}).get("slug") == "github-actions" and not META.search(r["name"])]


def raw(c):
    """Per-PR facts from GitHub, before the repository-level systematic rule."""
    repo, n = c["repo"], c["number"]
    commits = gh(f"repos/{repo}/pulls/{n}/commits?per_page=100")
    if not isinstance(commits, list):
        return {"excl": "error"}
    if any((x.get("author") or {}).get("login") != "dependabot[bot]" for x in commits):
        return {"excl": "human_commits"}
    head = runs(repo, c["head_sha"])
    if head is None:
        return {"excl": "error"}
    if any(r["status"] != "completed" for r in head):
        return {"excl": "pending"}
    done = {r["name"]: r["conclusion"] for r in head if r["conclusion"] not in IGNORE}
    if not done:
        return {"excl": "no_ci"}
    base = runs(repo, c["base_sha"]) or []
    bmap = {r["name"]: r["conclusion"] for r in base if r["status"] == "completed"}
    return {"head": done, "base": bmap}


def decide(items):
    """items: list of (cand, raw) of one repository -> list of label dicts."""
    ran, failed = defaultdict(int), defaultdict(int)
    for _, r in items:
        for name, concl in (r.get("head") or {}).items():
            ran[name] += 1
            failed[name] += concl in FAIL
    systematic = {k for k in ran if ran[k] >= 4 and failed[k] * 2 >= ran[k]}
    out = []
    for c, r in items:
        lab = {"repo": c["repo"], "number": c["number"]}
        if "excl" in r:
            lab.update(label=None, excl=r["excl"])
        else:
            fails = [k for k, v in r["head"].items() if v in FAIL and k not in systematic]
            ignored = [k for k, v in r["head"].items() if v in FAIL and k in systematic]
            attributable = [k for k in fails if r["base"].get(k) == "success"]
            succ = [k for k, v in r["head"].items() if v == "success"]
            if attributable:
                lab.update(label=1, failing_jobs=attributable)
            elif not fails:
                if succ:
                    lab.update(label=0, ignored_systematic=ignored)
                else:
                    lab.update(label=None, excl="no_ci")
            else:
                lab.update(label=None, excl="unattributable", failing_jobs=fails)
        out.append(lab)
    return out


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    cands = [json.loads(l) for l in open(src)]
    byrepo = defaultdict(list)
    for i, c in enumerate(cands):
        byrepo[c["repo"]].append((c, raw(c)))
        if i % 25 == 0:
            print(i, flush=True)
    with open(dst, "w") as f:
        for repo, items in byrepo.items():
            for lab in decide(items):
                f.write(json.dumps(lab) + "\n")
