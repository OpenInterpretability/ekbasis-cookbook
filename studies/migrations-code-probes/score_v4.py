"""v4: verdicts of OLD and NEW on a labelled set (D2 or T2), one regime at a time.

    python score_v4.py STATES_OLD STATES_NEW ANS_OLD ANS_NEW LABELS [--changed-only]

Verdict (the product's): decided "schema"/"fails_code" -> risky, reason fails; "cannot_foresee" -> risky (fail closed),
reason wrong; "ok_empty" -> ok; otherwise risky if p_lost >= 0.5 or p_fails >= 0.5 (or a schema error in autocommit),
reason "fails" when p_fails >= 0.5 or schema error, else "loses". NEW inherits OLD's answer when its state is byte-identical
(PREREG_v4 section 4). Truth: label_product; risky = lost or fails; true reason = fails if fails else loses.
"""
import json, sys
from math import comb

T = 0.5


def load(p):
    return {json.loads(l)["id"]: json.loads(l) for l in open(p)}


def verdict(st, ans):
    d = st.get("decided")
    if d in ("schema", "fails_code"):
        return True, "fails"
    if d in ("cannot_foresee", "missing"):
        return True, "cannot_foresee"
    if d == "ok_empty":
        return False, None
    if ans is None or "error" in ans:
        return None, None
    pf, pl = ans.get("p_fails", 0), ans.get("p_lost", 0)
    if st.get("schema_error_autocommit"):
        pf = 1.0
    if pf >= T:
        return True, "fails"
    if pl >= T:
        return True, "loses"
    return False, None


def mcnemar_one_sided(b, c):
    """P(X >= b) for X ~ Bin(b + c, 1/2): gains b, losses c."""
    n = b + c
    return sum(comb(n, k) for k in range(b, n + 1)) / 2 ** n if n else 1.0


def main():
    so, sn, ao, an, lp = sys.argv[1:6]
    changed_only = "--changed-only" in sys.argv
    SO, SN, AO, AN, L = load(so), load(sn), load(ao), load(an), load(lp)
    rows = []
    for i, lab in L.items():
        lp_ = lab["label_product"]
        risky = bool(lp_["lost"] or lp_["fails"])
        why = "fails" if lp_["fails"] else ("loses" if risky else None)
        same = SN[i].get("state") == SO[i].get("state") and SN[i].get("decided") == SO[i].get("decided")
        if changed_only and same:
            continue
        vo = verdict(SO[i], AO.get(i))
        vn = verdict(SN[i], AO.get(i) if same else AN.get(i))
        rows.append((i, risky, why, vo, vn, same))
    def stats(k):
        ben = [r for r in rows if not r[1] and r[k][0] is not None]
        rk = [r for r in rows if r[1] and r[k][0] is not None]
        fa = sum(r[k][0] for r in ben)
        rec = sum(r[k][0] for r in rk)
        exact = sum(1 for r in rk if r[k][0] and r[k][1] == r[2])
        acc = (sum(1 for r in rows if r[k][0] is not None and r[k][0] == r[1]))
        n = sum(1 for r in rows if r[k][0] is not None)
        return fa, len(ben), rec, len(rk), exact, acc, n
    for k, name in ((3, "OLD"), (4, "NEW")):
        fa, nb, rec, nr, ex, acc, n = stats(k)
        print(f"{name}: false alarms {fa}/{nb} = {fa / max(nb, 1):.3f}; recall {rec}/{nr} = {rec / max(nr, 1):.3f}; "
              f"reason exact {ex}/{max(rec, 1)}; accuracy {acc}/{n}")
    unanswered = [r[0] for r in rows if r[3][0] is None or r[4][0] is None]
    print("unanswered", len(unanswered), unanswered[:5], "| changed items", sum(1 for r in rows if not r[5]))
    ben_up = [r[0] for r in rows if not r[1] and r[4][0] and not r[3][0]]
    ben_down = [r[0] for r in rows if not r[1] and r[3][0] and not r[4][0]]
    rk_up = [r[0] for r in rows if r[1] and r[4][0] and not r[3][0]]
    rk_down = [r[0] for r in rows if r[1] and r[3][0] and not r[4][0]]
    print(f"benign: new alarms {len(ben_up)}, alarms removed {len(ben_down)} | risky: newly flagged {len(rk_up)}, "
          f"no longer flagged {len(rk_down)}")
    for lbl, xs in (("benign new alarm", ben_up), ("benign alarm removed", ben_down), ("risky newly flagged", rk_up),
                    ("risky lost", rk_down)):
        for x in xs:
            print(f"  {lbl}: {x}")


if __name__ == "__main__":
    main()
