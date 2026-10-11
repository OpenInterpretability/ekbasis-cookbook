import json, glob, collections
for p in sorted(glob.glob("data/items/*.jsonl")):
    if "slow" in p: continue
    rs = [json.loads(l) for l in open(p)]
    inc = [r for r in rs if not r.get("excluded")]
    ans = [r for r in inc if r["product"]["decided"] != "cannot_foresee_code"]
    risky = lambda r: r["label"]["lost"] or r["label"]["fails"]
    print(p.split("/")[-1], "n", len(rs), "excl", collections.Counter(e for r in rs for e in r.get("excluded", [])),
          "answered", len(ans), "risky_answered", sum(map(risky, ans)), "risky_all", sum(map(risky, inc)),
          "decided", collections.Counter(r["product"]["decided"] for r in inc))
