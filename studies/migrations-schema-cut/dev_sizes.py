import glob, json, sys, statistics as st
sys.path.insert(0, sys.argv[1])
from ekbasis import migrations as M
L=[]; capped=0; ntab=[]; others=[]
for p in glob.glob(sys.argv[2]+"/*.jsonl"):
    for l in open(p):
        r=json.loads(l); x=r.get("raw")
        if not x or "catalog" not in x: continue
        s,shown=M.build_state(x["catalog"],x["statements"],x["stats"],x["tool"],x["transaction"],[])
        L.append(len(s)); ntab.append(len(x["catalog"].get("tables") or []))
        named=M.named_tables("\n".join(x["statements"]),x["catalog"]["tables"] or [])
        if len(shown)>=M.MAX_TABLES: capped+=1
print("n",len(L),"median",st.median(L),"p95",sorted(L)[int(.95*len(L))],"max",max(L),">60k",sum(v>60000 for v in L),"capped at 8",capped,"median tables in schema",st.median(ntab),"max",max(ntab))
