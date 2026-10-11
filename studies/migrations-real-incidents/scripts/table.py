"""Step 3: classify every candidate and write table.jsonl (candidates first, then the screened-out commits).

Outcome for the guard (primary run: with the seeded replica's statistics):
  caught            - risky, with the reason class of the upstream problem (fails_* -> schema/fails; loss -> loses)
  caught_wrong_why  - risky, but for the other reason
  cannot_foresee    - the guard declined (fail closed: the PR is marked for a human)
  missed            - "ok" (or no verdict on the file)
  out_of_scope      - upstream problem was duration/locking, which the guard does not claim to foresee (its verdict is
                      still recorded)
  n/a               - no incident could be confirmed upstream (unknown), so neither caught nor missed
The same rule is applied to the regex baseline (F1 -> fails, R3 -> loses; both may fire).
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from candidates import C          # noqa: E402
from screened import S            # noqa: E402

FAIL = ("fails_data", "fails_schema", "fails_env")


def fileverdict(g, path):
    res = (g or {}).get("result") or {}
    f = next((x for x in res.get("files", []) if x.get("path") == path), None)
    return f, res


def outcome(up, kind):
    if up == "unknown":
        return "n/a"
    if up == "duration":
        return "out_of_scope"
    if kind == "cannot_foresee":
        return "cannot_foresee"
    if kind in (None, "ok"):
        return "missed"
    want = ("schema", "fails") if up in FAIL else ("loses",)
    return "caught" if kind in want else "caught_wrong_why"


def rules_outcome(up, r):
    if up == "unknown":
        return "n/a"
    if up == "duration":
        return "out_of_scope"
    if not (r["F1"] or r["R3"]):
        return "missed"
    ok = r["F1"] if up in FAIL else r["R3"]
    return "caught" if ok else "caught_wrong_why"


# Manual overrides, each with its reason (applied after reading the guard's stated reason).
OVERRIDE = {
    "hatchet-limits-overflow": ("flagged_spurious",
        "risky only because the probe ran the file in one transaction ('unsafe use of new value'); the file starts with "
        "'-- +goose NO TRANSACTION', so goose would not hit that error. The guard also ran the '-- +goose Down' section "
        "(comments are stripped). The real failures (integer overflow, missing ON CONFLICT) were not seen."),
}

rows = []
for c in C:
    p = os.path.join(HERE, "results", c["id"] + ".json")
    d = json.load(open(p)) if os.path.exists(p) else {"error": "not run"}
    f, res = fileverdict(d.get("guard_stats"), c["path"])
    f0, res0 = fileverdict(d.get("guard_nostats"), c["path"])
    kind = f["kind"] if f else None
    kind0 = f0["kind"] if f0 else None
    row = {
        "status": "candidate", "id": c["id"], "repo": c["gh"], "path": c["path"], "pr_head": d.get("head"),
        "pr_base": d.get("base"), "fix": c["fix"], "upstream": c["upstream"], "evidence": c["evidence"],
        "links": c["links"], "what_happened": c["note"],
        "guard": {"kind": kind, "reason": f and f["reason"], "p_lost": f and f["p_lost"], "p_fail": f and f["p_fail"],
                  "schema_error": f and f["schema_error"], "notes": (f or {}).get("notes", []) + res.get("notes", []),
                  "other_files": [x["path"] for x in res.get("files", []) if x.get("path") != c["path"]]},
        "guard_no_stats": {"kind": kind0, "p_lost": f0 and f0["p_lost"], "p_fail": f0 and f0["p_fail"]},
        "outcome": outcome(c["upstream"], kind), "outcome_no_stats": outcome(c["upstream"], kind0),
        "rules": d.get("rules"), "rules_outcome": rules_outcome(c["upstream"], d["rules"]) if d.get("rules") else None,
        "synthetic_label": d.get("synthetic"), "replica": d.get("replica"), "error": d.get("error"),
    }
    if c["id"] in OVERRIDE:
        row["outcome"], row["override_why"] = OVERRIDE[c["id"]]
        row["outcome_no_stats"] = row["outcome"]
    rows.append(row)
for repo, sha, why in S:
    rows.append({"status": "screened_out", "repo": repo, "commit": sha, "why": why})
with open(os.path.join(HERE, "table.jsonl"), "w") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")

from collections import Counter
cand = [r for r in rows if r["status"] == "candidate"]
print("candidates", len(cand), "screened", len(rows) - len(cand))
print("guard  ", Counter(r["outcome"] for r in cand))
print("nostats", Counter(r["outcome_no_stats"] for r in cand))
print("rules  ", Counter(r["rules_outcome"] for r in cand))
for r in cand:
    g = r["guard"]
    pl = "-" if g["p_lost"] is None else f"{g['p_lost']:.2f}"
    pf = "-" if g["p_fail"] is None else f"{g['p_fail']:.2f}"
    s = r["synthetic_label"] or {}
    print(f"{r['id']:<30} {r['upstream']:<12} {str(g['kind']):<15} L{pl} F{pf} -> {r['outcome']:<16} "
          f"nostats={r['outcome_no_stats']:<16} rules={r['rules_outcome']:<16} synth=f{int(bool(s.get('fails')))}"
          f"l{int(bool(s.get('lost')))} {r['error'] or ''}")
