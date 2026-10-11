"""Step 1: candidate Dependabot PRs (npm and pip), chosen from their title only, before any label.

Repos: GitHub repository search (TypeScript, JavaScript, Python; three star bands; pushed after 2026-09-20; not a fork,
not archived, under 150 MB). PRs: opened by dependabot[bot] after 2026-06-01, one package per PR ("Bump X from A to B"),
branch dependabot/npm_and_yarn/*, dependabot/pip/* or dependabot/uv/*.
"""
import json
import os
import re
import time

from ghc import ROOT, gh

SINCE = "2026-06-01"
TITLE = re.compile(r"[Bb]ump (?P<pkg>\S+) from (?P<frm>v?[0-9][\w.\-+]*) to (?P<to>v?[0-9][\w.\-+]*)(?: in (?P<dir>\S+))?\s*$")
ECO = {"npm_and_yarn": "npm", "pip": "pip", "uv": "pip"}


def repos():
    out = {}
    for lang in ("TypeScript", "JavaScript", "Python"):
        for band in ("100..500", "500..3000", "3000..40000"):
            for page in (1, 2):
                q = f"language:{lang} stars:{band} pushed:>2026-09-20 archived:false fork:false size:<150000"
                url = f"search/repositories?q={q.replace(' ', '+')}&per_page=100&page={page}"
                d = gh(url)
                time.sleep(2.2)
                for r in d.get("items", []):
                    out[r["full_name"]] = {"repo": r["full_name"], "lang": lang, "stars": r["stargazers_count"],
                                           "size_kb": r["size"], "default_branch": r["default_branch"]}
    return list(out.values())


def prs(repo):
    found = []
    for page in (1, 2):
        d = gh(f"repos/{repo}/pulls?state=all&sort=created&direction=desc&per_page=100&page={page}")
        if not isinstance(d, list) or not d:
            break
        for p in d:
            if p["created_at"] < SINCE:
                return found
            if (p.get("user") or {}).get("login") != "dependabot[bot]":
                continue
            ref = p["head"]["ref"]
            parts = ref.split("/")
            if len(parts) < 3 or parts[0] != "dependabot" or parts[1] not in ECO:
                continue
            m = TITLE.search(p["title"])
            if not m or " group" in p["title"]:
                continue
            found.append({"repo": repo, "number": p["number"], "title": p["title"], "pkg": m["pkg"],
                          "frm": m["frm"].lstrip("v"), "to": m["to"].lstrip("v"), "dir": m["dir"] or "/",
                          "eco": ECO[parts[1]], "created": p["created_at"], "head_sha": p["head"]["sha"],
                          "base_sha": p["base"]["sha"], "base_ref": p["base"]["ref"], "state": p["state"],
                          "merged": bool(p.get("merged_at"))})
        if len(d) < 100:
            break
    return found


if __name__ == "__main__":
    rs = repos()
    print("repos", len(rs))
    with open(os.path.join(ROOT, "data", "repos.jsonl"), "w") as f:
        for r in rs:
            f.write(json.dumps(r) + "\n")
    from concurrent.futures import ThreadPoolExecutor
    n = 0
    with open(os.path.join(ROOT, "data", "candidates_all.jsonl"), "w") as f, ThreadPoolExecutor(8) as ex:
        for i, (r, found) in enumerate(zip(rs, ex.map(lambda r: prs(r["repo"]), rs))):
            for c in found:
                c["lang"], c["stars"] = r["lang"], r["stars"]
                f.write(json.dumps(c) + "\n")
                n += 1
            if i % 100 == 0:
                print(i, n, flush=True)
    print("candidates", n)
