"""Mecanismo (c): migrações que removem ou mudam o tipo de uma coluna (ou removem a tabela) que uma view lê.
    python3 view_mech.py ITEMS_DIR [IDS_FILE]   -> ids, e se o OLD mostrava a view (nunca: o OLD não tem views)"""
import glob, json, re, sys
sys.path.insert(0, "ekbasis")
from ekbasis import migrations as M
want = None
if len(sys.argv) > 2:
    want = {json.loads(l)["id"] for l in open(sys.argv[2])}
hits = []
for p in sorted(glob.glob(sys.argv[1] + "/*.jsonl")):
    for l in open(p):
        r = json.loads(l); x = r.get("raw") or {}
        if "catalog" not in x or (want and r["id"] not in want):
            continue
        cat = x["catalog"]
        byoid = {str(t["oid"]): t for t in cat["tables"]}
        cut = M.schema_cut(cat, x["statements"])
        if not isinstance(cut, M.Cut):
            continue
        reads = {}
        for v in cat.get("views") or []:
            for o, col in v.get("deps") or []:
                if str(o) in byoid:
                    reads.setdefault((byoid[str(o)]["name"].lower(), (col or "").lower()), []).append(v["name"])
        text = " ".join(M.outside_bodies(s) for s in x["statements"])
        found = []
        for m in re.finditer(r'ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?:"?\w+"?\.)?"?(\w+)"?(.*?)(?=ALTER\s+TABLE|$)', text, re.I | re.S):
            t = m.group(1).lower()
            for c in re.finditer(r'(?:DROP\s+(?:COLUMN\s+)?(?:IF\s+EXISTS\s+)?|ALTER\s+(?:COLUMN\s+)?)"?(\w+)"?(\s+(?:SET\s+DATA\s+)?TYPE)?', m.group(2), re.I):
                if c.group(0).upper().startswith("DROP") or c.group(2):
                    if (t, c.group(1).lower()) in reads:
                        found.append(f"{t}.{c.group(1)} read by {reads[(t, c.group(1).lower())]}")
        for m in re.finditer(r'DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?"?(\w+)"?', text, re.I):
            if any(k[0] == m.group(1).lower() for k in reads):
                found.append(f"drop table {m.group(1)} read by a view")
        if found:
            hits.append((r["id"], found, x.get("schema_error")))
for h in hits:
    print(h)
print(len(hits), "items")
