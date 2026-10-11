"""Step 4: the facts about one PR, extracted by code only (PREREG §4). Nothing here reads the CI result.

Sources: the PR (title, body with Dependabot's release notes and changelog, changed files with their diffs), the
package's GitHub releases between the two versions, the package registry (npm or PyPI) for both versions, and the
repository's files at the PR's base commit (codeload tarball, source and config files only).
"""
import html
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.parse

from ghc import ROOT, gh, http_json

SRC = os.path.join(ROOT, "cache", "src")
NPM_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte", ".astro")
PY_EXT = (".py", ".pyi")
CONF = ("package.json", "tsconfig.json", ".nvmrc", ".node-version", "pyproject.toml", "setup.cfg", "setup.py",
        "tox.ini", "noxfile.py", ".python-version", "Makefile")
SKIP_DIRS = {"node_modules", "dist", "build", "vendor", ".next", "coverage", "out", "site-packages", ".venv", "venv",
             "third_party", "__pycache__", ".git"}
LOCKS = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json", "uv.lock", "poetry.lock",
         "Pipfile.lock", "bun.lock")
KEYWORDS = re.compile(r"\b(breaking|BREAKING|removed?|removing|drop(ped|s)?|deprecat\w*|no longer|renamed?|"
                      r"minimum|requires? (node|python)|esm[- ]only|pure esm|incompatib\w*|migrat\w*)\b", re.I)
MAX_NOTE_LINES = 14
MAX_SYMBOLS = 8
PY_MODULES = {"pyyaml": "yaml", "beautifulsoup4": "bs4", "pillow": "PIL", "scikit-learn": "sklearn",
              "python-dateutil": "dateutil", "opencv-python": "cv2", "opencv-python-headless": "cv2",
              "protobuf": "google.protobuf", "attrs": "attr", "pyjwt": "jwt", "python-dotenv": "dotenv",
              "typing-extensions": "typing_extensions", "msgpack-python": "msgpack", "pymupdf": "fitz",
              "python-multipart": "multipart", "google-cloud-storage": "google.cloud.storage", "psycopg2-binary": "psycopg2",
              "djangorestframework": "rest_framework", "pyopenssl": "OpenSSL", "markdown": "markdown"}


# ---------------------------------------------------------------- versions

def vparts(v):
    m = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", v or "")
    return tuple(int(x or 0) for x in m.groups()) if m else None


def semver_delta(frm, to):
    a, b = vparts(frm), vparts(to)
    if not a or not b:
        return "unknown"
    if a[0] != b[0]:
        return "major"
    if a[0] == 0 and a[1] != b[1]:
        return "major"            # 0.x: a minor change is a breaking change by semver
    if a[1] != b[1]:
        return "minor"
    return "patch"


# ---------------------------------------------------------------- release notes

def text_lines(body_html):
    """Dependabot's HTML/markdown -> plain lines (one per <li>, <p> or heading)."""
    body_html = (body_html or "").replace("\r\n", "\n")
    # join hard-wrapped lines (markdown, and RST changelogs quoted in Dependabot's HTML); a list item, a heading, a
    # tag or a blank line starts a new line
    body_html = re.sub(r"\n(?![ \t]*(?:[-*+] |\d+\.|#|<|\n))[ \t]*", " ", body_html)
    t = re.sub(r"<code>(.*?)</code>", lambda m: "`" + m.group(1) + "`", body_html or "", flags=re.S)
    t = re.sub(r"</?(li|p|h\d|br|tr|blockquote|ul|ol|details|summary)[^>]*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("​", "")
    out = []
    for line in t.splitlines():
        line = re.sub(r"\s+", " ", line).strip(" -*#>")
        line = re.sub(r"\(?\[?#\d+\]?(\([^)]*\))?\)?", "", line)      # PR refs
        line = re.sub(r"\s+by @\S+.*$", "", line)
        line = re.sub(r"https?://\S+", "", line).strip()
        if len(line) > 3:
            out.append(line)
    return out


def note_lines(lines):
    seen, out = set(), []
    for line in lines:
        if len(line) < 15 or re.match(r"`?[0-9a-f]{7,40}`?\s", line):
            continue              # a bare heading, or a commit line from the "Commits" list
        if not KEYWORDS.search(line) or line.lower().startswith(("sourced from", "bumps ", "updates the requirements")):
            continue
        if re.search(r"\b(dependabot|ci:|chore\(deps|bump (the )?\S+ from)\b", line, re.I):
            continue
        line = re.sub(r"\(?\[?`?\b[0-9a-f]{5,40}\b`?\]?\(?\)?", "", line)   # commit hashes and their links
        line = re.sub(r"\]\(\s*$|\s*[,(]\s*(?=[,)]|$)", "", line).strip(" ,(")
        if len(line) < 15:
            continue
        short = line[:220] + ("..." if len(line) > 220 else "")
        k = re.sub(r"[^a-z0-9]+", "", short.lower())[:60]
        if k not in seen:
            seen.add(k)
            out.append(short)
    return out


def src_repo(body):
    m = re.search(r"Bumps \[[^\]]+\]\((https://github\.com/[^/\s)]+/[^/\s)#]+)", body or "")
    return m.group(1).replace("https://github.com/", "").rstrip("/") if m else None


def releases_between(srepo, pkg, frm, to):
    """Bodies of the source repository's releases with frm < version <= to (no pre-releases)."""
    a, b = vparts(frm), vparts(to)
    if not srepo or not a or not b:
        return []
    d = gh(f"repos/{srepo}/releases?per_page=100")
    if not isinstance(d, list):
        return []
    short = pkg.split("/")[-1]
    out = []
    for r in d:
        tag = r.get("tag_name") or ""
        if r.get("prerelease") or r.get("draft"):
            continue
        if "@" in tag.lstrip("@") and short not in tag:
            continue                # monorepo tag of another package
        if re.search(r"[a-z]-v?\d", tag) and short not in tag and pkg.split("/")[0].lstrip("@") not in tag:
            continue
        m = re.findall(r"(\d+\.\d+(?:\.\d+)?)", tag)
        v = vparts(m[-1]) if m else None
        if v and a < v <= b:
            out.append((v, r.get("body") or ""))
    return [body for _, body in sorted(out)]


# ---------------------------------------------------------------- repository files

_LOCK = threading.Lock()
_LOCKS = {}


def fetch_src(repo, sha, eco):
    with _LOCK:
        lock = _LOCKS.setdefault((repo, sha), threading.Lock())
    with lock:
        return _fetch_src(repo, sha, eco)


def _fetch_src(repo, sha, eco):
    dest = os.path.join(SRC, repo.replace("/", "__") + "@" + sha[:12])
    if os.path.exists(os.path.join(dest, ".done")):
        return dest
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    exts = NPM_EXT if eco == "npm" else PY_EXT
    inc = [f"*{e}" for e in exts] + [f"*{c}" for c in CONF] + ["*requirements*.txt", "*.github/workflows/*",
                                                               "*eslint*", "*.config.*", "*rc.json", "*rc.js"]
    args = ["tar", "-xzf", "-", "-C", dest, "--strip-components", "1"]
    for x in ("*/node_modules/*", "*/dist/*", "*/vendor/*", "*.min.js", "*/.venv/*", "*/site-packages/*"):
        args += ["--exclude", x]
    for x in inc:
        args += ["--include", x]
    url = f"https://codeload.github.com/{repo}/tar.gz/{sha}"
    curl = subprocess.Popen(["curl", "-sfL", "--max-time", "600", url], stdout=subprocess.PIPE)
    r = subprocess.run(args, stdin=curl.stdout, capture_output=True)
    curl.wait()
    if curl.returncode != 0:
        return None
    open(os.path.join(dest, ".done"), "w").close()
    return dest


def walk(dest):
    for root, dirs, files in os.walk(dest):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not (d.startswith(".") and d != ".github")]
        for f in files:
            p = os.path.join(root, f)
            if os.path.getsize(p) > 400_000:
                continue
            yield os.path.relpath(p, dest), p


def read(p):
    try:
        with open(p, errors="replace") as f:
            return f.read()
    except OSError:
        return ""


# ---------------------------------------------------------------- registry

def npm_meta(pkg, ver):
    name = pkg.replace("/", "%2F") if pkg.startswith("@") else pkg
    d = http_json(f"https://registry.npmjs.org/{name}/{ver}")
    return d if "__error__" not in d else None


def pypi_meta(pkg, ver):
    d = http_json(f"https://pypi.org/pypi/{pkg}/{ver}/json")
    return d.get("info") if "__error__" not in d else None


def range_min_major(rng):
    """Smallest major a range like '>=18', '^18.18.0 || >=20' or '>=3.10' allows (first number), None if unknown."""
    nums = []
    for part in re.split(r"\|\||,", rng or ""):
        part = part.strip()
        if part.startswith(("!=", "<")):
            continue
        for tok in part.split():
            if tok.startswith("<"):
                continue
            m = re.match(r"(?:>=|\^|~=|~|>|==|=)?\s*v?(\d+)(?:\.(\d+))?", tok)
            if m:
                nums.append((int(m.group(1)), int(m.group(2) or 0)))
                break
    return min(nums) if nums else None


def range_majors(rng):
    return sorted({int(x) for x in re.findall(r"(?:^|[\s|^~>=<])v?(\d+)(?:\.[\dxX*]+)*", rng or "")})


# ---------------------------------------------------------------- lockfile diff

def lock_changes(fname, patch, main_pkg):
    """{package: (old, new)} for packages whose version a lockfile patch changes (the upgraded package excluded)."""
    ch = {}
    cur = None
    base = os.path.basename(fname)
    for line in (patch or "").splitlines():
        body = line[1:] if line[:1] in "+- " else line
        sign = line[:1]
        if base in ("package-lock.json", "npm-shrinkwrap.json"):
            m = re.match(r'\s*"(?:.*node_modules/)?((?:@[^/"]+/)?[^/"]+)": \{', body)
            if m and "node_modules/" in body:
                cur = m.group(1)
            m = re.match(r'\s*"version": "([^"]+)"', body)
            if m and cur and sign in "+-":
                o, n = ch.get(cur, (None, None))
                ch[cur] = (m.group(1), n) if sign == "-" else (o, m.group(1))
        elif base == "yarn.lock":
            m = re.match(r'^"?((?:@[^/@"]+/)?[^@"\s]+)@', body)
            if m and not body.startswith(" "):
                cur = m.group(1)
            m = re.match(r'\s+version:? "?([^"\s]+)"?', body)
            if m and cur and sign in "+-":
                o, n = ch.get(cur, (None, None))
                ch[cur] = (m.group(1), n) if sign == "-" else (o, m.group(1))
        elif base == "pnpm-lock.yaml":
            m = re.match(r"^\s+'?/?((?:@[^/@']+/)?[^@/'\s]+)@(\d[^:('\s]*)", body)
            if m and sign in "+-" and body.rstrip().endswith(":"):
                o, n = ch.get(m.group(1), (None, None))
                ch[m.group(1)] = (m.group(2), n) if sign == "-" else (o, m.group(2))
        elif base in ("uv.lock", "poetry.lock"):
            m = re.match(r'name = "([^"]+)"', body)
            if m:
                cur = m.group(1)
            m = re.match(r'version = "([^"]+)"', body)
            if m and cur and sign in "+-":
                o, n = ch.get(cur, (None, None))
                ch[cur] = (m.group(1), n) if sign == "-" else (o, m.group(1))
        elif base.startswith("requirements") or base.endswith(".txt"):
            m = re.match(r"([A-Za-z0-9_.\-\[\]]+)==([^\s;\\]+)", body)
            if m and sign in "+-":
                k = re.sub(r"\[.*\]", "", m.group(1)).lower()
                o, n = ch.get(k, (None, None))
                ch[k] = (m.group(2), n) if sign == "-" else (o, m.group(2))
    norm = lambda s: re.sub(r"[-_.]+", "-", s.lower())
    return {k: v for k, v in ch.items() if v[0] != v[1] and norm(k) != norm(main_pkg)}


# ---------------------------------------------------------------- the facts

def import_regex(eco, pkg):
    if eco == "npm":
        name = pkg[len("@types/"):] if pkg.startswith("@types/") else pkg
        if name != pkg and "__" in name:
            name = "@" + name.replace("__", "/")
        q = re.escape(name)
        return re.compile(r"""(?:from\s+|require\(\s*|import\(\s*|import\s+)['"]""" + q + r"""(?:/[^'"]*)?['"]""")
    mod = PY_MODULES.get(pkg.lower(), re.sub(r"[-.]", "_", pkg.lower()))
    q = re.escape(mod)
    return re.compile(r"^\s*(?:from\s+" + q + r"(?:\.\S+)?\s+import\b|import\s+" + q + r"\b)", re.M | re.I)


def symbols(lines, pkg):
    out = []
    for line in lines:
        dotted = [d for d in re.findall(r"(?<![\w$.`/])([A-Za-z_$][\w$]*\.[A-Za-z_$][\w$]{2,})(?![\w$`(/])", line)
                  if not re.search(r"\.(js|ts|mjs|cjs|json|md|py|toml|yml|yaml|txt|cfg|ini|lock|html|css|io|com|org|dev)$",
                                   d, re.I)]
        for s in re.findall(r"`([^`]{2,60})`", line) + dotted:
            s = s.strip().rstrip("()").strip()
            s = re.sub(r"\(.*$", "", s)
            if not re.fullmatch(r"[A-Za-z_$@][\w$.\-/:@#]*", s) or len(s) < 3:
                continue
            if s.lower() in (pkg.lower(), "node", "npm", "true", "false", "null", "undefined", "python", "none",
                             "pip", "yarn", "pnpm", "esm", "cjs", "commonjs", "module", "require", "import", "export"):
                continue
            if s.startswith("@") and "/" not in s:
                continue            # a GitHub user
            if re.fullmatch(r"[0-9a-f]{7,40}", s) or re.fullmatch(r"v?\d[\d.x]*", s) or s.startswith("@") and "/" in s and s.count("/") == 1 and "." not in s:
                continue
            if s not in out:
                out.append(s)
    return out[:MAX_SYMBOLS]


def workflows(files):
    """(workflow text of the workflows that run on pull requests, run commands, node versions, python versions)."""
    texts = [t for rel, t in files.items() if rel.startswith(".github/workflows/") and "pull_request" in t]
    runs, node, py = [], set(), set()
    for t in texts:
        for m in re.finditer(r"^(\s*)-?\s*run:\s*(\|[-+]?|>[-+]?)?\s*(.*)$", t, re.M):
            if m.group(2):
                ind = len(m.group(1))
                rest = t[m.end():].splitlines()[1:]
                cmd = [x.strip() for x in rest[:3] if x.strip() and (len(x) - len(x.lstrip())) > ind]
                cmd = "; ".join(cmd[:2])
            else:
                cmd = m.group(3).strip()
            if cmd and not re.match(r"(echo|if|fi|then|else|done|for|cat|\"|'|#|\$\{\{)", cmd) and cmd not in runs:
                runs.append(cmd[:120])
        for key, acc in (("node", node), ("python", py)):
            for m in re.finditer(key + r"(?:-version|_version)?s?\s*:\s*(\[[^\]]*\]|[^\n#]+)", t, re.I):
                for v in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)(?:\.x)?(?![\w])", m.group(1)):
                    if key == "python" and not v.startswith("3."):
                        continue
                    if key == "node" and not (8 <= int(v.split(".")[0]) <= 30):
                        continue
                    acc.add(v)
    return texts, runs, node, py


def pr_facts(c, verbose=False):
    repo, n, eco, pkg, frm, to = c["repo"], c["number"], c["eco"], c["pkg"], c["frm"], c["to"]
    pr = gh(f"repos/{repo}/pulls/{n}")
    body = pr.get("body") or ""
    files = gh(f"repos/{repo}/pulls/{n}/files?per_page=100")
    files = files if isinstance(files, list) else []
    dest = fetch_src(repo, c["base_sha"], eco)
    tree = {rel: read(p) for rel, p in walk(dest)} if dest else {}
    F = {"delta": semver_delta(frm, to), "src_missing": dest is None}

    # release notes: Dependabot's body plus the package's GitHub releases between the versions
    lines = text_lines(body)
    srepo = src_repo(body)
    for rb in releases_between(srepo, pkg, frm, to):
        lines += text_lines(rb)
    notes = note_lines(lines)
    F["notes"] = notes[:MAX_NOTE_LINES]
    F["notes_total"] = len(notes)
    F["release_notes_seen"] = bool(re.search(r"Release notes|Changelog", body)) or bool(srepo)
    F["breaking_word"] = any(re.search(r"breaking", x, re.I) for x in notes)

    # where the dependency is declared
    d = (c.get("dir") or "/").strip("/")
    decl = []
    if eco == "npm":
        pj = tree.get(os.path.join(d, "package.json") if d else "package.json")
        try:
            pjd = json.loads(pj) if pj else {}
        except ValueError:
            pjd = {}
        for sec in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            if pkg in (pjd.get(sec) or {}):
                decl.append(f'{sec} "{pjd[sec][pkg]}"')
        F["repo_module_type"] = pjd.get("type", "commonjs")
        F["repo_engines_node"] = (pjd.get("engines") or {}).get("node")
    changed = [f["filename"] for f in files]
    F["changed_files"] = changed
    F["declared"] = decl

    # registry: runtime requirements, module format, peer dependencies
    rt = []
    if eco == "npm":
        a, b = npm_meta(pkg, frm), npm_meta(pkg, to)
        if b:
            en_a = ((a or {}).get("engines") or {}).get("node")
            en_b = (b.get("engines") or {}).get("node")
            F["engines_from"], F["engines_to"] = en_a, en_b
            if (a or {}).get("type") != "module" and b.get("type") == "module":
                F["became_esm"] = True
                F["esm_only"] = "require" not in json.dumps(b.get("exports") or {})
            pa, pb = (a or {}).get("peerDependencies") or {}, b.get("peerDependencies") or {}
            F["peer_changes"] = {k: (pa.get(k), v) for k, v in pb.items() if pa.get(k) != v}
            F["deprecated"] = b.get("deprecated")
            da, db = (a or {}).get("dependencies") or {}, b.get("dependencies") or {}
            F["deps_added"] = sorted(set(db) - set(da))
            F["deps_removed"] = sorted(set(da) - set(db))
    else:
        a, b = pypi_meta(pkg, frm), pypi_meta(pkg, to)
        if b:
            F["engines_from"] = (a or {}).get("requires_python")
            F["engines_to"] = b.get("requires_python")
            ra = {re.split(r"[\s;<>=!~\[(]", x)[0].lower() for x in ((a or {}).get("requires_dist") or []) if "extra ==" not in x}
            rb = {re.split(r"[\s;<>=!~\[(]", x)[0].lower() for x in (b.get("requires_dist") or []) if "extra ==" not in x}
            F["deps_added"], F["deps_removed"] = sorted(rb - ra), sorted(ra - rb)

    # CI
    wtexts, runs, node, py = workflows(tree)
    F["ci_workflows"] = len(wtexts)
    F["ci_runs"] = runs[:12]
    F["ci_node"], F["ci_python"] = sorted(node, key=vparts), sorted(py, key=vparts)
    for f in (".nvmrc", ".node-version"):
        if f in tree and re.match(r"v?\d+", tree[f].strip()):
            F["ci_node"] = sorted(set(F["ci_node"]) | {re.match(r"v?(\d+)", tree[f].strip()).group(1)}, key=vparts)
    if eco == "pip":
        pp = tree.get("pyproject.toml", "")
        m = re.search(r'requires-python\s*=\s*"([^"]+)"', pp) or re.search(r"python_requires\s*=\s*['\"]?([^'\"\n]+)",
                                                                           tree.get("setup.cfg", "") + tree.get("setup.py", ""))
        F["repo_requires_python"] = m.group(1) if m else None
        if ".python-version" in tree:
            v = re.match(r"(3\.\d+)", tree[".python-version"].strip())
            if v:
                F["ci_python"] = sorted(set(F["ci_python"]) | {v.group(1)}, key=vparts)
    need = range_min_major(F.get("engines_to"))
    had = range_min_major(F.get("engines_from"))
    F["runtime_raised"] = bool(need and had and need > had) or bool(need and not had and F.get("engines_to"))
    ci_v = F["ci_node"] if eco == "npm" else F["ci_python"]
    below = []
    if need:
        for v in ci_v:
            p = vparts(v)
            if p and ((p[0], p[1]) < need if eco == "pip" else p[0] < need[0]):
                below.append(v)
    F["ci_below_min"] = below

    # peers against what the repository declares
    if eco == "npm" and F.get("peer_changes"):
        allpj = {}
        for rel, t in tree.items():
            if rel.endswith("package.json") and "/node_modules/" not in rel:
                try:
                    j = json.loads(t)
                except ValueError:
                    continue
                for sec in ("dependencies", "devDependencies"):
                    for k, v in (j.get(sec) or {}).items():
                        allpj.setdefault(k, v)
        mism = []
        for k, (old, new) in F["peer_changes"].items():
            have = allpj.get(k)
            if not have:
                continue
            hm = vparts(re.sub(r"^[^\d]*", "", have))
            maj = range_majors(new)
            if hm and maj and hm[0] not in maj and not (re.search(r">=?\s*v?" + str(min(maj)), new) and hm[0] >= min(maj)):
                mism.append((k, new, have))
        F["peer_mismatch"] = mism

    # lockfile
    lk, lock_files, lock_too_big = {}, [], []
    for f in files:
        base = os.path.basename(f["filename"])
        if base in LOCKS or (eco == "pip" and base.endswith(".txt")):
            lock_files.append(f["filename"])
            if "patch" not in f and base in LOCKS:
                lock_too_big.append((f["filename"], f.get("additions"), f.get("deletions")))
            lk.update(lock_changes(f["filename"], f.get("patch"), pkg))
    trans = []
    for k, (o, nn) in lk.items():
        if o and nn:
            trans.append((k, o, nn, semver_delta(o, nn)))
        elif nn:
            trans.append((k, None, nn, "added"))
        else:
            trans.append((k, o, None, "removed"))
    order = {"major": 0, "added": 1, "removed": 2, "minor": 3, "patch": 4, "unknown": 5}
    trans.sort(key=lambda x: (order[x[3]], x[0]))
    F["lock_files"], F["lock_too_big"], F["transitive"] = lock_files, lock_too_big, trans

    # usage in the repository
    exts = NPM_EXT if eco == "npm" else PY_EXT
    rx = import_regex(eco, pkg)
    importers = [rel for rel, t in tree.items() if rel.endswith(exts) and rx.search(t)]
    F["importers"] = sorted(importers)
    spec = re.compile(r"""['"](""" + re.escape(pkg) + r"""/[^'"]+)['"]""") if eco == "npm" else None
    F["subpaths"] = sorted({m for rel in importers for m in spec.findall(tree[rel])}) if spec else []
    if eco == "npm":
        rq = re.compile(r"""require\(\s*['"]""" + re.escape(pkg) + r"""(?:/[^'"]*)?['"]\s*\)""")
        F["requirers"] = sorted(rel for rel in importers if rq.search(tree[rel]))
    mention = re.compile(r"(?<![\w@/.-])" + re.escape(pkg) + r"(?![\w-])")
    F["mentions"] = sorted(rel for rel, t in tree.items()
                           if rel not in importers and not rel.endswith(LOCKS) and os.path.basename(rel) not in LOCKS
                           and "requirements" not in rel and not rel.endswith("package.json") and mention.search(t))
    syms = symbols(notes, pkg)
    hits = []
    scope = importers or [rel for rel in tree if rel.endswith(exts)]
    for s in syms:
        last = re.split(r"[./:#]", s)[-1]
        if len(last) < 3:
            continue
        srx = re.compile(r"(?<![\w$])" + re.escape(last) + r"(?![\w$])")
        cnt, ex = 0, []
        for rel in scope:
            for i, line in enumerate(tree[rel].splitlines()):
                if srx.search(line):
                    cnt += 1
                    if len(ex) < 2:
                        ex.append(f"{rel}:{i + 1}: {line.strip()[:110]}")
        hits.append({"symbol": s, "searched": last, "count": cnt, "examples": ex,
                     "where": "files that import the package" if importers else "all source files"})
    F["symbol_hits"] = hits
    F["ts"] = any(r.endswith("tsconfig.json") for r in tree)
    F["n_source_files"] = sum(1 for r in tree if r.endswith(exts))
    return F
