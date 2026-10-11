"""A1 check: the rebuilt items against the stale build (labels, render, decisions, exclusions)."""
import json, sys
for p in sys.argv[1:]:
    a = {r["path"]: r for r in map(json.loads, open(f"data/items_stale/{p}.jsonl"))}
    b = {r["path"]: r for r in map(json.loads, open(f"data/items/{p}.jsonl"))}
    d = {k: 0 for k in ("label", "sql", "decided", "excluded", "missing")}
    for k, x in a.items():
        y = b.get(k)
        if not y:
            d["missing"] += 1; continue
        d["label"] += x["label"] != y["label"]
        d["sql"] += x["render"]["sql"] != y["render"]["sql"]
        d["decided"] += x["product"]["decided"] != y["product"]["decided"]
        d["excluded"] += x["excluded"] != y["excluded"]
        if x["label"] != y["label"] or x["excluded"] != y["excluded"]:
            print("  diff", k, x["label"], y["label"], x["excluded"], y["excluded"])
    print(p, len(a), len(b), d)
