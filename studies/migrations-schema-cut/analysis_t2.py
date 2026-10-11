"""T2: critérios do PREREG §6 por regime, tokens, latência, itens que mudaram, mecanismo view (c)."""
import json, random, re, statistics as st, sys
from math import comb

LAB = {json.loads(l)["id"]: json.loads(l) for l in open("../v4/data/labels_v3.jsonl")}
ANS = {}
for l in open("data/ans_t2.jsonl"):
    r = json.loads(l)
    if "error" not in r:
        ANS[(r["arm"], r["regime"], r["id"])] = r


def load(p):
    return {json.loads(l)["id"]: json.loads(l) for l in open(p)}


def verdict(s, a):
    d = s.get("decided")
    if d == "schema":
        return True, "fails"
    if d == "cannot_foresee":
        return True, "cannot_foresee"
    if d == "ok_empty":
        return False, None
    if a is None:
        return True, "cannot_foresee"           # PREREG: unanswered = fail closed
    pf, pl = a["p_fails"], a["p_lost"]
    if s.get("schema_error_autocommit"):
        pf = 1.0
    if pf >= 0.5:
        return True, "fails"
    if pl >= 0.5:
        return True, "loses"
    return False, None


def mcnemar(b, c):
    n = b + c
    if not n:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def ptiles(xs):
    xs = sorted(xs)
    return f"median {st.median(xs):.0f} (p10 {xs[len(xs)//10]:.0f}, p90 {xs[9*len(xs)//10]:.0f})"


def timing(r, k="model"):
    m = re.search(k + r";dur=([0-9.]+)", r.get("server_timing") or "")
    return float(m.group(1)) if m else None


overall = True
for reg in "RN":
    O, N = load(f"data/st_old.{reg}.jsonl"), load(f"data/st_new.{reg}.jsonl")
    rows = []
    unanswered = {"old": 0, "new": 0}
    for i, lab in LAB.items():
        lp = lab["label_product"]
        risky = bool(lp["lost"] or lp["fails"])
        why = "fails" if lp["fails"] else ("loses" if risky else None)
        same = N[i]["state"] == O[i]["state"] and N[i]["decided"] == O[i]["decided"]
        ao = ANS.get(("old", reg, i))
        an = ao if same else ANS.get(("new", reg, i))
        if O[i]["questions"] and ao is None: unanswered["old"] += 1
        if N[i]["questions"] and an is None: unanswered["new"] += 1
        rows.append(dict(id=i, risky=risky, why=why, o=verdict(O[i], ao), n=verdict(N[i], an), same=same, ao=ao, an=an))
    def m(k):
        fa = sum(r[k][0] for r in rows if not r["risky"])
        rec = sum(r[k][0] for r in rows if r["risky"])
        ex = sum(1 for r in rows if r["risky"] and r[k][0] and r[k][1] == r["why"])
        acc = sum(r[k][0] == r["risky"] for r in rows)
        return fa, rec, ex, acc
    fo, ro, eo, ao_ = m("o"); fn, rn, en, an_ = m("n")
    nb, nr, n = sum(not r["risky"] for r in rows), sum(r["risky"] for r in rows), len(rows)
    b = sum(1 for r in rows if (r["n"][0] == r["risky"]) and (r["o"][0] != r["risky"]))
    c = sum(1 for r in rows if (r["o"][0] == r["risky"]) and (r["n"][0] != r["risky"]))
    rng = random.Random(20261011)
    d = [(r["n"][0] == r["risky"]) - (r["o"][0] == r["risky"]) for r in rows]
    boots = sorted(sum(d[rng.randrange(n)] for _ in range(n)) / n for _ in range(10000))
    lo, hi = boots[249], boots[9749]
    diff = (an_ - ao_) / n
    c1, c2, c3, c4 = diff >= -0.02, fn <= fo + 3, rn >= ro - 2, en >= eo - 2
    overall &= c1 and c2 and c3 and c4
    print(f"== regime {reg} (n={n}; benign {nb}, risky {nr}; unanswered old {unanswered['old']} new {unanswered['new']})")
    print(f"OLD: acc {ao_}/{n} = {ao_/n:.3f}; false alarms {fo}/{nb}; recall {ro}/{nr}; reason exact {eo}")
    print(f"NEW: acc {an_}/{n} = {an_/n:.3f}; false alarms {fn}/{nb}; recall {rn}/{nr}; reason exact {en}")
    print(f"C1 acc diff {diff*100:+.1f} pp (95% bootstrap CI {lo*100:+.1f} .. {hi*100:+.1f}); McNemar b={b} c={c} p={mcnemar(b, c):.3f} -> {'PASS' if c1 else 'FAIL'}"
          + ("" if lo >= -0.02 else "  [CI lower bound below -2 pp: non-inferiority not shown statistically]"))
    print(f"C2 false alarms {fn} vs {fo}+3 -> {'PASS' if c2 else 'FAIL'}; C3 recall {rn} vs {ro}-2 -> {'PASS' if c3 else 'FAIL'}; "
          f"C4 reason {en} vs {eo}-2 -> {'PASS' if c4 else 'FAIL'}")
    # tokens and latency, on items both arms asked (paired)
    pairs = [(ANS[("old", reg, r["id"])], ANS[("new", reg, r["id"])]) for r in rows
             if ("old", reg, r["id"]) in ANS and ("new", reg, r["id"]) in ANS]
    tok = lambda a: (a.get("usage") or {}).get("prompt_tokens") or (a.get("usage") or {}).get("input_tokens")
    to = [tok(a) for a, _ in pairs if tok(a)]; tn = [tok(b) for _, b in pairs if tok(b)]
    if to and tn:
        red = [1 - tok(b) / tok(a) for a, b in pairs if tok(a) and tok(b)]
        print(f"input tokens ({len(pairs)} paired): OLD {ptiles(to)} | NEW {ptiles(tn)} | paired reduction median {st.median(red)*100:.1f}% "
              f"(p10 {sorted(red)[len(red)//10]*100:.1f}%, p90 {sorted(red)[9*len(red)//10]*100:.1f}%); totals {sum(to):,} -> {sum(tn):,}")
    so = [a["secs"] for a, _ in pairs]; sn = [b["secs"] for _, b in pairs]
    print(f"wall secs: OLD median {st.median(so):.1f} | NEW median {st.median(sn):.1f}")
    for k in ("model", "queue"):
        mo = [timing(a, k) for a, _ in pairs if timing(a, k) is not None]; mn = [timing(b, k) for _, b in pairs if timing(b, k) is not None]
        if mo and mn:
            print(f"server-timing {k}: OLD median {st.median(mo):.0f} ms | NEW median {st.median(mn):.0f} ms")
    for r in rows:
        if r["o"] != r["n"]:
            tag = ("benign" if not r["risky"] else f"risky/{r['why']}")
            po = (round(r["ao"]["p_lost"], 2), round(r["ao"]["p_fails"], 2)) if r["ao"] else None
            pn = (round(r["an"]["p_lost"], 2), round(r["an"]["p_fails"], 2)) if r["an"] else None
            ok = lambda v: "right" if (v[0] == r["risky"] and (not r["risky"] or v[1] == r["why"])) else "wrong"
            print(f"  changed [{tag}] {r['id']}: OLD {r['o']} {po} {ok(r['o'])} -> NEW {r['n']} {pn} {ok(r['n'])}")
    # mechanism (c): items whose NEW state shows a dependent view
    vc = [r for r in rows if "Views that depend on them" in (N[r["id"]]["state"] or "")]
    print(f"items with dependent views in NEW: {len(vc)}; OLD right {sum(r['o'][0]==r['risky'] for r in vc)}, NEW right {sum(r['n'][0]==r['risky'] for r in vc)}; "
          f"risky among them {sum(r['risky'] for r in vc)}")
    print()
print("DECISION:", "all criteria pass in both regimes -> recommend the cut as default" if overall else "a criterion failed -> the cut stays off by default")
