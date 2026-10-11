"""Exploratory (not registered): tokens, Ekbasis against R2, strata, mechanism facts, clusters. usage: explore.py test"""
import json
import sys
from collections import Counter

from analysis import auroc, cluster_boot, load, metrics

split = sys.argv[1] if len(sys.argv) > 1 else "test"
rows, lab = load(split)
F = {d["id"]: d["facts"] for d in map(json.loads, open(f"data/{split}_facts.jsonl"))}
A = {d["id"]: d for d in map(json.loads, open(f"data/{split}_answers.jsonl"))}
y = [r["y"] for r in rows]
for r in rows:
    r["s"] = r["s_max"]
    r["ek"] = r["s"] >= 0.2
toks = [A[r["id"]]["usage"]["input_tokens"] for r in rows]
lat = sorted(A[r["id"]]["latency_s"] for r in rows)
print("input tokens", sum(toks), "mean", round(sum(toks) / len(toks)), "latency p50", lat[len(lat) // 2], "p90", lat[int(.9 * len(lat))])
print("AUROC of R1 as a score", round(auroc(y, [int(r["r1"]) for r in rows]), 3), "R2", round(auroc(y, [int(r["r2"]) for r in rows]), 3))
# graded rule: 2 = major+breaking, 1 = major, 0 = other
g = [2 * r["r2"] + (r["r1"] and not r["r2"]) for r in rows]
print("AUROC of graded rule (major+breaking > major > other)", round(auroc(y, g), 3),
      cluster_boot([dict(r, g=gg) for r, gg in zip(rows, g)], lambda rs: auroc([x["y"] for x in rs], [x["g"] for x in rs])))
print("Ekbasis AUROC", round(auroc(y, [r["s"] for r in rows]), 3))
for name, sub in (("R2 positive", [r for r in rows if r["r2"]]), ("major, no 'breaking'", [r for r in rows if r["r1"] and not r["r2"]]),
                  ("not major", [r for r in rows if not r["r1"]])):
    print(f"  stratum {name}: n={len(sub)} pos={sum(r['y'] for r in sub)} AUROC={auroc([r['y'] for r in sub], [r['s'] for r in sub]):.3f}",
          "ek", metrics([r["y"] for r in sub], [r["ek"] for r in sub]))
# agreement with R2
print("verdict agreement Ekbasis vs R2:", sum(r["ek"] == r["r2"] for r in rows), "/", len(rows))


def mech(f):
    m = []
    if f.get("peer_mismatch"):
        m.append("peer_mismatch")
    if f.get("ci_below_min"):
        m.append("runtime_below_min")
    if f.get("esm_only") and f.get("requirers"):
        m.append("esm_only_required")
    if any(h["count"] for h in f.get("symbol_hits", [])):
        m.append("named_symbol_used")
    return m


print("\nPRs with a concrete mechanism fact:")
for k in ("peer_mismatch", "runtime_below_min", "esm_only_required", "named_symbol_used", "none"):
    sub = [r for r in rows if (k in mech(F[r["id"]])) or (k == "none" and not mech(F[r["id"]]))]
    if sub:
        print(f"  {k}: n={len(sub)} broken={sum(r['y'] for r in sub)} mean s broken={sum(r['s'] for r in sub if r['y']) / max(1, sum(r['y'] for r in sub)):.2f}"
              f" not broken={sum(r['s'] for r in sub if not r['y']) / max(1, sum(1 - r['y'] for r in sub)):.2f} flagged={sum(r['ek'] for r in sub)}")
print("\npositives per repository:", Counter(r["repo"] for r in rows if r["y"]).most_common(8))
print("\nfalse negatives (broken, s<0.2):")
for r in sorted(rows, key=lambda r: r["s"]):
    if r["y"] and not r["ek"]:
        f = F[r["id"]]
        print(f"  {r['id']} {f['delta']} notes={len(f['notes'])} imp={len(f['importers'])} mech={mech(f)} s={r['s']:.2f} jobs={[j[:30] for j in lab[r['id']]['failing_jobs'][:2]]}")
print("\ntrue positives:")
for r in rows:
    if r["y"] and r["ek"]:
        f = F[r["id"]]
        print(f"  {r['id']} {f['delta']} notes={len(f['notes'])} mech={mech(f)} s={r['s']:.2f}")
print("\nfalse alarms with s>=0.5:")
for r in sorted(rows, key=lambda r: -r["s"]):
    if not r["y"] and r["s"] >= 0.5:
        f = F[r["id"]]
        print(f"  {r['id']} {f['delta']} mech={mech(f)} s={r['s']:.2f}")

print("\nexploratory code-only rules built from the same facts (NOT registered, chosen after seeing the test):")
def M(f):
    m = mech(f)
    return bool({"peer_mismatch", "runtime_below_min", "esm_only_required"} & set(m))
for name, fn in (("M: peer/runtime/ESM fact", lambda r, f: M(f)),
                 ("M or (major and named symbol used)", lambda r, f: M(f) or (r["major"] and "named_symbol_used" in mech(f))),
                 ("R2 or M", lambda r, f: r["r2"] or M(f))):
    print(" ", name, metrics(y, [fn(r, F[r["id"]]) for r in rows]))
