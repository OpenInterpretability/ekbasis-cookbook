"""Step 5: the state and the questions sent to Ekbasis (PREREG §4-5). The state holds only facts from facts.py."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))  # ekbasis 0.1.16 from PyPI
from ekbasis import prompts as P  # noqa: E402

ECO_NAME = {"npm": "npm", "pip": "PyPI"}
RULES = ("A software repository with continuous integration (CI) on GitHub Actions. A pull request opened by Dependabot "
         "changes only dependency files: it upgrades one package (the manifest and the lockfile). The CI workflows run "
         "on the pull request's commit. Every fact below was collected by code from the pull request, the package's "
         "release notes, the package registry and the repository's files before the upgrade; a fact that is not "
         "listed was not found.")

QUESTIONS = {
    "api": P.yes_no("Will a CI job fail because code in this repository uses an API of the upgraded package that this "
                    "upgrade removes or changes?"),
    "other": P.yes_no("Will a CI job fail for another reason introduced by this upgrade (installation, build, type "
                      "checking, lint, tests, or a runtime version the new release no longer supports)?"),
    "any": P.yes_no("Will any CI job fail on this pull request?"),
}


def lst(xs, k=5):
    xs = list(xs)
    return ", ".join(xs[:k]) + (f" and {len(xs) - k} more" if len(xs) > k else "")


def build_state(c, F):
    eco, pkg, frm, to = c["eco"], c["pkg"], c["frm"], c["to"]
    rt = "Node.js" if eco == "npm" else "Python"
    s = []
    s.append(f"Repository: {F['n_source_files']} {'JavaScript/TypeScript' if eco == 'npm' else 'Python'} source files"
             + (" (TypeScript, tsconfig.json present)." if eco == "npm" and F.get("ts") else "."))
    kind = {"major": "a semver-major upgrade" + (" (a 0.x minor change)" if frm.startswith("0.") else ""),
            "minor": "a semver-minor upgrade", "patch": "a semver-patch upgrade", "unknown": "an upgrade"}[F["delta"]]
    s.append(f"Upgrade: {ECO_NAME[eco]} package {pkg} from {frm} to {to}, {kind}.")
    if F.get("declared"):
        s.append(f"Declared in {c.get('dir') or '/'}package.json as " + "; ".join(F["declared"]) + ".")
    s.append("Files the pull request changes: " + lst(F["changed_files"], 6) + ".")

    # release notes
    if F["notes"]:
        more = f" ({F['notes_total'] - len(F['notes'])} more not shown)" if F["notes_total"] > len(F["notes"]) else ""
        s.append("Release notes between the two versions, the lines that mention breaking changes, removals, "
                 "deprecations, renames or requirements" + more + ":")
        s += [f"- {x}" for x in F["notes"]]
    elif F["release_notes_seen"]:
        s.append("Release notes between the two versions: no line mentions a breaking change, a removal, a "
                 "deprecation, a rename or a new requirement.")
    else:
        s.append("Release notes: none available.")

    # runtime
    if F.get("engines_to") or F.get("engines_from"):
        s.append(f"Required {rt} version (registry): {F.get('engines_from') or 'not stated'} before, "
                 f"{F.get('engines_to') or 'not stated'} after the upgrade.")
    ci_v = F["ci_node"] if eco == "npm" else F["ci_python"]
    if ci_v:
        s.append(f"{rt} versions set in the CI workflows: {', '.join(ci_v)}.")
    if F.get("ci_below_min"):
        s.append(f"{rt} versions in CI below the new release's minimum: {', '.join(F['ci_below_min'])}.")
    elif ci_v and F.get("engines_to"):
        s.append(f"Every {rt} version in CI meets the new release's minimum.")
    if eco == "pip" and F.get("repo_requires_python"):
        s.append(f"The repository declares requires-python {F['repo_requires_python']}.")
    if eco == "npm" and F.get("repo_engines_node"):
        s.append(f"The repository's package.json declares engines.node {F['repo_engines_node']}.")

    # module format, peers, deprecation
    if F.get("became_esm"):
        s.append("Module format: the new release is an ES module package (\"type\": \"module\"); the old one was not."
                 + (" Its exports have no \"require\" condition (ESM-only)." if F.get("esm_only") else ""))
        if F.get("esm_only"):
            r = F.get("requirers") or []
            s.append(f"Files in the repository that load it with require(): {len(r)}" + (f" ({lst(r, 3)})." if r else ".")
                     + f" The repository's package.json type is \"{F.get('repo_module_type', 'commonjs')}\".")
    if F.get("peer_changes"):
        s.append("Peer dependencies changed: " + "; ".join(f"{k} {o or 'none'} -> {n}" for k, (o, n) in
                                                             list(F["peer_changes"].items())[:5]) + ".")
    for k, need, have in F.get("peer_mismatch") or []:
        s.append(f"Peer mismatch: the new release requires {k} {need}; the repository declares {k} {have}.")
    if F.get("deprecated"):
        s.append(f"The registry marks the new release as deprecated: {F['deprecated'][:150]}")
    if F.get("deps_added") or F.get("deps_removed"):
        s.append("The package's own dependencies: " + ("added " + lst(F["deps_added"], 4) if F.get("deps_added") else "")
                 + ("; " if F.get("deps_added") and F.get("deps_removed") else "")
                 + ("removed " + lst(F["deps_removed"], 4) if F.get("deps_removed") else "") + ".")

    # lockfile
    tr = F["transitive"]
    if tr:
        def one(t):
            k, o, n, d = t
            return f"{k} {o} -> {n} ({d})" if o and n else (f"{k} {n} (added)" if n else f"{k} {o} (removed)")
        s.append(f"Other packages the lockfile changes: {len(tr)}: " + lst([one(t) for t in tr], 8) + ".")
    elif F["lock_too_big"]:
        f, a, d = F["lock_too_big"][0]
        s.append(f"The lockfile diff ({f}, +{a} -{d} lines) is too large to be read.")
    elif F["lock_files"]:
        s.append("The lockfile changes no other package.")

    # usage
    imp = F["importers"]
    s.append(f"Source files that import {pkg}: {len(imp)}" + (f" ({lst(imp, 4)})." if imp else "."))
    if F.get("subpaths"):
        s.append(f"Subpath imports of {pkg} in the repository: " + lst(F["subpaths"], 5) + ".")
    if F["mentions"]:
        s.append(f"Other files that name {pkg} (config, scripts, workflows): " + lst(F["mentions"], 5) + ".")
    for h in F["symbol_hits"]:
        if h["count"]:
            s.append(f"Name `{h['symbol']}` from the release notes: found {h['count']} times in {h['where']}, e.g. "
                     + " | ".join(h["examples"]) + ".")
        else:
            s.append(f"Name `{h['symbol']}` from the release notes: not found in {h['where']}.")

    # CI
    if F["ci_workflows"]:
        s.append(f"CI on pull requests: {F['ci_workflows']} workflow(s); "
                 + ("commands: " + "; ".join(F["ci_runs"][:10]) + "." if F["ci_runs"] else "no run command found in them."))
    else:
        s.append("CI on pull requests: no workflow file that names pull_request was found (the CI may run from a "
                 "reusable workflow).")
    state = "\n".join(s)
    action = f"Merge this pull request's changes (upgrade {pkg} from {frm} to {to}) and run the CI jobs on the result."
    return P.world_state(RULES, state, [action])
