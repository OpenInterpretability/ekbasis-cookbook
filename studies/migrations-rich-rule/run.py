"""Run R_RICH on a split. Dev: scores against the dev labels. Test: writes predictions only (no labels read).

    python3 run.py dev [--errors]           -> dev metrics, regimes R and N
    python3 run.py test OUT_PREFIX          -> OUT_PREFIX.{R,N}.jsonl  {"id", "p_fails", "p_lost", "kind", "why"}
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import facts as F   # noqa: E402
import rule as R    # noqa: E402

sys.path.insert(0, os.path.join(SP, "p2"))
from score_v4 import verdict   # noqa: E402  the product's verdict, unchanged


def predict(raw, regime):
    f = F.view(raw, regime)
    try:
        kind, why = R.decide(f)
    except Exception as e:      # never skip an item: a crash is an "ok" with the error noted
        kind, why = "ok", [f"rule error {type(e).__name__}: {e}"]
    return {"p_fails": 1.0 if kind == "fails" else 0.0, "p_lost": 1.0 if kind == "loses" else 0.0, "kind": kind,
            "why": why}


def load(p):
    return {json.loads(l)["id"]: json.loads(l) for l in open(p)}


def dev(show):
    import glob
    items, labs = {}, {}
    for p in glob.glob(os.path.join(SP, "p2/data/items_d2/*.jsonl")):
        for l in open(p):
            r = json.loads(l)
            items[r["id"]] = r["raw"]
            labs[r["id"]] = r["label_tx"] if r["raw"]["transaction"] else r["label_auto"]
    for reg in "RN":
        st = load(os.path.join(SP, f"p2/st/d2_new.{reg}.jsonl"))
        tp = fp = fn = tn = ex = 0
        errs = []
        for i, raw in items.items():
            if i not in st or st[i].get("decided") == "missing":
                continue
            pr = predict(raw, reg)
            v = verdict(st[i], pr)
            lab = labs[i]
            risky = bool(lab["lost"] or lab["fails"])
            why = "fails" if lab["fails"] else ("loses" if risky else None)
            if v[0] and risky:
                tp += 1
                ex += v[1] == why
                if v[1] != why:
                    errs.append(("REASON", i, why, v[1], pr["why"]))
            elif v[0]:
                fp += 1
                errs.append(("FA", i, why, v[1], pr["why"]))
            elif risky:
                fn += 1
                errs.append(("MISS", i, why, v[1], pr["why"]))
            else:
                tn += 1
        n = tp + fp + fn + tn
        print(f"{reg}: n={n} acc={(tp + tn) / n:.3f} recall={tp}/{tp + fn} FA={fp}/{fp + tn} reason_exact={ex}/{tp}")
        if show:
            for e in sorted(errs):
                print("  ", e[0], e[1], "true:", e[2], "pred:", e[3], "|", "; ".join(e[4])[:300])


def test(prefix):
    import glob
    items = F.load(os.path.join(SP, "p2/data/items_p2"))       # labels dropped by the loader
    ids = [json.loads(l)["id"] for l in open(os.path.join(SP, "p2/st/t2_new.R.jsonl"))]
    for reg in "RN":
        with open(f"{prefix}.{reg}.jsonl", "w") as f:
            for i in ids:
                f.write(json.dumps({"id": i, **predict(items[i]["raw"], reg)}) + "\n")


if __name__ == "__main__":
    if sys.argv[1] == "dev":
        dev("--errors" in sys.argv)
    else:
        test(sys.argv[2])
