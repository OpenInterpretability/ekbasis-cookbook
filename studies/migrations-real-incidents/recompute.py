"""Recomputes the result table of this study from the released per-candidate records (table.jsonl).

    python recompute.py      # standard library only; writes recompute_output.txt and compares it with table_summary.txt

For every candidate it re-derives the outcome from the upstream class and the guard's verdict kind (with and without
the replica's statistics), and the regex baseline's outcome from its R3/F1 flags, with the rules of scripts/table.py.
It checks that each re-derived outcome equals the stored one, then prints the same summary as table_summary.txt.
"""
from __future__ import annotations

import io
import json
import os
from collections import Counter
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
FAIL = ("fails_data", "fails_schema", "fails_env")


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


def main():
    rows = [json.loads(l) for l in open(os.path.join(HERE, "table.jsonl"))]
    cand = [r for r in rows if r["status"] == "candidate"]
    bad = []
    for r in cand:
        o, o0 = outcome(r["upstream"], r["guard"]["kind"]), outcome(r["upstream"], r["guard_no_stats"]["kind"])
        if r.get("override_why"):                    # the one manual override (hatchet), with its reason in the row
            o = o0 = r["outcome"]
        ro = rules_outcome(r["upstream"], r["rules"]) if r.get("rules") else None
        for name, got, want in (("outcome", o, r["outcome"]), ("outcome_no_stats", o0, r["outcome_no_stats"]),
                                ("rules_outcome", ro, r["rules_outcome"])):
            if got != want:
                bad.append((r["id"], name, got, want))

    buf = io.StringIO()
    with redirect_stdout(buf):
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
        inscope = [r for r in cand if r["outcome"] not in ("n/a", "out_of_scope")]
        print(f"\nin scope (confirmed failure or loss): {len(inscope)}")
        for col in ("outcome", "outcome_no_stats", "rules_outcome"):
            c = Counter(r[col] for r in inscope)
            flagged = c["caught"] + c["caught_wrong_why"] + c["flagged_spurious"]
            print(f"  {col:<17} flagged {flagged}/{len(inscope)} (right reason {c['caught']}), "
                  f"cannot foresee {c['cannot_foresee']}, missed {c['missed']}")
        print("\nre-derived outcomes that differ from the stored ones:", bad or "none")
    out = buf.getvalue()
    open(os.path.join(HERE, "recompute_output.txt"), "w").write(out)
    print(out, end="")
    ref = open(os.path.join(HERE, "table_summary.txt")).read()
    same = out.startswith(ref)
    print("matches table_summary.txt:", "yes" if same else "NO")
    raise SystemExit(0 if same and not bad else 1)


if __name__ == "__main__":
    main()
