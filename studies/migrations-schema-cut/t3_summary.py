import collections, json, statistics as st
R = [json.loads(l) for l in open("data/t3.jsonl")]
print(f"{'repo':12s} {'mig':>4s} {'state':>5s} {'tab max':>7s} {'OLD>60k':>7s} {'NEW>60k':>7s} {'gain':>4s} {'fb':>3s} {'med OLD':>7s} {'med NEW':>7s} {'ratio':>5s}  decided")
tot = collections.Counter(); reasons = collections.Counter(); ratios = []
for repo in dict.fromkeys(r["repo"] for r in R):
    rs = [r for r in R if r["repo"] == repo]
    s = [r for r in rs if "old" in r]
    o = sum(r["old"] > 60000 for r in s); n = sum(r["new"] > 60000 for r in s)
    g = sum(r["old"] > 60000 >= r["new"] for r in s)
    fb = [r for r in s if r["fallback"]]
    for r in fb:
        reasons[r["fallback"].split(":")[0] if "cannot resolve" not in r["fallback"] else "unresolved names"] += 1
    rr = [r["new"] / r["old"] for r in s if not r["fallback"]]
    ratios += rr
    dec = collections.Counter(r.get("decided") for r in rs if r.get("decided"))
    tot.update(mig=len(rs), state=len(s), old=o, new=n, gain=g, fb=len(fb))
    print(f"{repo:12s} {len(rs):4d} {len(s):5d} {max([r['tables'] for r in s] or [0]):7d} {o:7d} {n:7d} {g:4d} {len(fb):3d} "
          f"{st.median([r['old'] for r in s] or [0]):7.0f} {st.median([r['new'] for r in s] or [0]):7.0f} "
          f"{(st.median(rr) if rr else 0):5.2f}  {dict(dec)}")
print("total", dict(tot), "| ratio NEW/OLD median %.2f p10 %.2f p90 %.2f" % (st.median(ratios), sorted(ratios)[len(ratios)//10], sorted(ratios)[9*len(ratios)//10]))
print("max OLD", max(r.get("old", 0) for r in R), "max NEW", max(r.get("new", 0) for r in R))
for k, v in reasons.most_common():
    print(f"  {v:3d} {k[:120]}")
for r in R:
    if r.get("fallback") and "cannot resolve" in r["fallback"]:
        print("   ", r["repo"], r["path"][-50:], r["fallback"][:150])
