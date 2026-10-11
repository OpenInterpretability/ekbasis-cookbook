"""Sem modelo: estados OLD (_named_state = build_state do 0.1.17) e NEW (corte) sobre itens reconstruídos.
    python compare_states.py ITEMS_DIR [--show N]"""
import collections, glob, json, statistics as st, sys
sys.path.insert(0, "ekbasis")
from ekbasis import migrations as M

rows = []
same_inputs = 0
for p in sorted(glob.glob(sys.argv[1] + "/*.jsonl")):
    for l in open(p):
        r = json.loads(l)
        x = r.get("raw")
        if not x or "catalog" not in x:
            continue
        same_inputs += bool(r.get("v4_same_inputs"))
        old, oshown = M._named_state(x["catalog"], x["statements"], x["stats"], x["tool"], x["transaction"], [])
        notes = []
        new, nshown = M.build_state(x["catalog"], x["statements"], x["stats"], x["tool"], x["transaction"], [], notes)
        cut = M.schema_cut(x["catalog"], x["statements"])
        byoid = {str(t["oid"]): M.disp(t) for t in x["catalog"]["tables"]}
        touched = [byoid[o] for o in cut.touched] if isinstance(cut, M.Cut) else []
        rows.append(dict(id=r["id"], old=len(old), new=len(new), fb=notes[0] if notes else None,
                         dropped=[t for t in touched if t not in oshown], extra=[t for t in oshown if t not in nshown],
                         views="Views that depend" in new, trig="Triggers on them" in new, brief="Tables linked to them" in new,
                         ntables=len(x["catalog"]["tables"]), oshown=oshown, nshown=nshown))
n = len(rows)
print(f"items with a state: {n}; same tables/enums as v4: {same_inputs}")
fb = [r for r in rows if r["fb"]]
print(f"fallback (not cut): {len(fb)} ({len(fb)/n:.1%})")
for k, v in collections.Counter(r["fb"].split(":")[0] if "cannot resolve" not in r["fb"] else "unresolved names"
                                for r in fb).most_common(12):
    print(f"   {v:4d}  {k[:110]}")
cutr = [r for r in rows if not r["fb"]]
print(f"cut: {len(cutr)}")
ratio = [r["new"] / r["old"] for r in cutr]
print(f"chars OLD median {st.median(r['old'] for r in rows):.0f} NEW median {st.median(r['new'] for r in rows):.0f}; "
      f"NEW/OLD on cut items: median {st.median(ratio):.2f}, p10 {sorted(ratio)[len(ratio)//10]:.2f}, "
      f"p90 {sorted(ratio)[9*len(ratio)//10]:.2f}; NEW shorter {sum(x<1 for x in ratio)}, same {sum(x==1 for x in ratio)}, longer {sum(x>1 for x in ratio)}")
print(f"> MAX_CHARS: OLD {sum(r['old']>M.MAX_CHARS for r in rows)}, NEW {sum(r['new']>M.MAX_CHARS for r in rows)}; "
      f"max OLD {max(r['old'] for r in rows)} NEW {max(r['new'] for r in rows)}")
print(f"touched table missing from OLD (cap of 8 / regex): {sum(bool(r['dropped']) for r in cutr)}")
print(f"OLD shows a table NEW does not (regex false match or beyond 1 FK step): {sum(bool(r['extra']) for r in cutr)}")
print(f"NEW has views {sum(r['views'] for r in cutr)}, triggers {sum(r['trig'] for r in cutr)}, FK-line neighbors {sum(r['brief'] for r in cutr)}")
if "--show" in sys.argv:
    k = int(sys.argv[sys.argv.index("--show") + 1])
    for r in [r for r in cutr if r["dropped"]][:k]:
        print("DROPPED", r["id"], r["dropped"], "| old", r["oshown"])
    for r in [r for r in cutr if r["extra"]][:k]:
        print("EXTRA", r["id"], r["extra"], "| new", r["nshown"])
    for r in fb[:k]:
        print("FB", r["id"], r["fb"][:160])
