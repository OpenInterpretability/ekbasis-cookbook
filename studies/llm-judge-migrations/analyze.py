"""Registered analysis (PREREG.md): EKB (schema-cut study answers, arm new) vs GLM judge, same states and verdict code."""
import json, random, re, statistics as st, os
SC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAB = {json.loads(l)["id"]: json.loads(l) for l in open(f"{SC}/v4/data/labels_v3.jsonl")}
EKB = {}
for l in open(f"{SC}/corte_schema/data/ans_t2.jsonl"):
    r = json.loads(l)
    if "error" not in r:
        EKB[(r["arm"], r["regime"], r["id"])] = r

def verdict(s, a):
    d = s.get("decided")
    if d == "schema": return True, "fails"
    if d == "cannot_foresee": return True, "cannot_foresee"
    if d == "ok_empty": return False, None
    if a is None or "error" in a: return True, "cannot_foresee"
    pf, pl = a["p_fails"], a["p_lost"]
    if s.get("schema_error_autocommit"): pf = 1.0
    if pf >= 0.5: return True, "fails"
    if pl >= 0.5: return True, "loses"
    return False, None

def auroc(pairs):
    pos = [p for p, y in pairs if y]; neg = [p for p, y in pairs if not y]
    if not pos or not neg: return float("nan")
    return sum((a > b) + 0.5 * (a == b) for a in pos for b in neg) / (len(pos) * len(neg))

def ms(t):
    m = re.search(r"model;dur=([0-9.]+)", t or ""); return float(m.group(1)) / 1000 if m else None

for reg in "RN":
    path = f"glm.{reg}.jsonl"
    if not os.path.exists(path): continue
    S = {json.loads(l)["id"]: json.loads(l) for l in open(f"{SC}/corte_schema/data/st_new.{reg}.jsonl")}
    O = {json.loads(l)["id"]: json.loads(l) for l in open(f"{SC}/corte_schema/data/st_old.{reg}.jsonl")}
    G = {}
    for l in open(path):                     # last completed record per id; infrastructure errors are not answers
        r = json.loads(l)
        if "infra_error" in r or str(r.get("error", "")).startswith("HTTPError"):
            G.setdefault(r["id"], None)
        else:
            G[r["id"]] = r
    infra = [i for i, r in G.items() if r is None]
    G = {i: r for i, r in G.items() if r is not None}
    if infra: print(f"  ({reg}) {len(infra)} items with only infrastructure errors, left out: {infra[:5]}")
    rows = []
    for i, lab in LAB.items():
        if i not in G: continue
        lp = lab["label_product"]; risky = bool(lp["lost"] or lp["fails"])
        why = "fails" if lp["fails"] else ("loses" if risky else None)
        same = S[i]["state"] == O[i]["state"] and S[i]["decided"] == O[i]["decided"]
        e = EKB.get(("old", reg, i)) if same else EKB.get(("new", reg, i))
        rows.append(dict(id=i, risky=risky, why=why, lp=lp, e=e, g=G[i], ve=verdict(S[i], e), vg=verdict(S[i], G[i])))
    n = len(rows)
    def m(k):
        acc = sum(r[k][0] == r["risky"] for r in rows); rec = sum(r[k][0] for r in rows if r["risky"])
        fa = sum(r[k][0] for r in rows if not r["risky"]); ex = sum(1 for r in rows if r["risky"] and r[k][0] and r[k][1] == r["why"])
        return acc, rec, fa, ex
    nr = sum(r["risky"] for r in rows); nb = n - nr
    me, mg = m("ve"), m("vg")
    d = [(r["ve"][0] == r["risky"]) - (r["vg"][0] == r["risky"]) for r in rows]
    rng = random.Random(20261011)
    bs = sorted(sum(d[rng.randrange(n)] for _ in range(n)) / n for _ in range(10000))
    print(f"== regime {reg}: n={n} (risky {nr}, benign {nb}); GLM errors {sum('error' in r['g'] for r in rows)}")
    for name, mm in (("EKB", me), ("GLM", mg)):
        print(f"  {name}: accuracy {mm[0]/n:.3f}  recall {mm[1]}/{nr}  false alarms {mm[2]}/{nb}  reason exact {mm[3]}")
    diff = (me[0] - mg[0]) / n
    print(f"  C1 EKB-GLM accuracy {diff*100:+.1f} pp, 95% CI [{bs[249]*100:+.1f}, {bs[9749]*100:+.1f}] -> {'PASS' if diff >= -0.02 else 'FAIL'}")
    br = {}
    for name, key in (("EKB", "e"), ("GLM", "g")):
        b, au = [], []
        for q, lk in (("p_lost", "lost"), ("p_fails", "fails")):
            pr = [(r[key][q], bool(r["lp"][lk])) for r in rows if r[key] and "error" not in r[key]]
            b.append(st.mean((p - y) ** 2 for p, y in pr)); au.append(auroc(pr))
        br[name] = st.mean(b)
        print(f"  {name}: AUROC lost {au[0]:.3f} fails {au[1]:.3f}; Brier lost {b[0]:.4f} fails {b[1]:.4f}")
    print(f"  C2 Brier EKB {br['EKB']:.4f} <= GLM {br['GLM']:.4f} -> {'PASS' if br['EKB'] <= br['GLM'] else 'FAIL'}")
    el = [ms(r["e"].get("server_timing")) for r in rows if r["e"] and ms(r["e"].get("server_timing"))]
    gl = [r["g"]["secs"] for r in rows if "secs" in r["g"]]
    go = [r["g"]["out"] for r in rows if r["g"].get("out")]
    print(f"  latency median: EKB model {st.median(el):.2f} s | GLM {st.median(gl):.2f} s; GLM output tokens median {st.median(go):.0f} (EKB 0)")
