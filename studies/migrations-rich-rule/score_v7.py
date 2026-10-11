"""Retest on 0.1.21 (PREREG_v7rr.md). Reads labels. python3 score_v7.py EKB.json > results_v7rr.txt"""
import glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); SP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import load_v7 as L, facts_cut as C, rule, rule_noseed     # noqa: E402
import score_fw as S                                         # noqa: E402  (stats, compare: same code as the held-out)

OK_KIND = {"fails": "fails", "schema": "fails", "loses": "loses"}


def rule_v(f, mod, schema_error):
    kind = mod.decide(f)[0]
    if schema_error or kind == "fails":
        return True, "fails"
    return (True, "loses") if kind == "loses" else (False, "ok")


def arms_for(ids, E, F, SE):
    arms = {k: {} for k in ("a EKB", "b R_RICH", "c R_NOSEED", "d POLICY", "e NOSEED OR EKB")}
    warn = {}
    for i in ids:
        e = tuple(E[i]); arms["a EKB"][i] = e
        if F[i] is None:                         # decided by the product: the same verdict in every arm
            b = c = e
        else:
            b, c = rule_v(F[i], rule, SE[i]), rule_v(F[i], rule_noseed, SE[i])
        arms["b R_RICH"][i] = b; arms["c R_NOSEED"][i] = c; arms["d POLICY"][i] = c
        warn[i] = bool(e[0]) and not c[0] and F[i] is not None
        arms["e NOSEED OR EKB"][i] = c if c[0] else e
    return arms, warn


def report(title, ids, arms, warn, T, choose):
    print(f"\n== {title}: n = {len(ids)}, risky {sum(T[i][0] for i in ids)}")
    summ = {}
    for k, V in arms.items():
        s, o = S.stats(ids, V, T, warn if k.startswith("d") else None)
        print(f"  {k:<16} {s}"); summ[k] = o
    print("  " + S.compare(ids, arms["a EKB"], arms["c R_NOSEED"], T, "EKB", "R_NOSEED"))
    print("  " + S.compare(ids, arms["a EKB"], arms["b R_RICH"], T, "EKB", "R_RICH"))
    if choose:
        er = summ["a EKB"]["rec"]
        print("  product policy (PREREG_v7rr §6):")
        elig = []
        for k, o in summ.items():
            ok = not k.startswith("b") and o["fa"] <= 0.15 and o["recw"] >= er - 1e-12
            if ok:
                elig.append((k, o))
            print(f"    {k:<16} acc {o['acc']:.3f} FA {o['fa']:.3f} recall w/ warnings {o['recw']:.3f} (EKB {er:.3f}) "
                  f"{'ELIGIBLE' if ok else ('not a candidate' if k.startswith('b') else 'not eligible')}")
        print("    chosen:", sorted(elig, key=lambda x: (-x[1]["acc"], -x[1]["recw"], x[1]["warn_ben"]))[0][0]
              if elig else "none eligible")
    print("  errors (truth | EKB | R_NOSEED | warn):")
    for i in ids:
        e, c = arms["a EKB"][i], arms["c R_NOSEED"][i]
        if bool(e[0]) != T[i][0] or bool(c[0]) != T[i][0]:
            print(f"    {i} | {T[i][1]} | {e[1] if e[0] else 'ok'} | {c[1] if c[0] else 'ok'} | {'W' if warn[i] else ''}")


def main():
    E = json.load(open(sys.argv[1]))
    # Rails v7 (held-out, primary)
    rows, states = L.v7_items()
    lab = {}
    for p in glob.glob(os.path.join(L.R7, "eval", "data", "items", "*.jsonl")):
        for l in open(p):
            r = json.loads(l); lab[f"{r['project']}/{r['path']}"] = r["label"]
    ids, F, SE, T, unconv = [], {}, {}, {}, []
    for r in rows:
        i = r["id"]
        if E["v7"][i][1] == "code_not_foreseen":
            continue
        f = None
        if not r["product"]["decided"]:
            try:
                f = L.v7_facts(r, states)
            except C.Unconvertible:
                unconv.append(i); continue
        ids.append(i); F[i] = f; SE[i] = bool(r["product"].get("schema_error"))
        lb = lab[i]; T[i] = (bool(lb["fails"] or lb["lost"]), "fails" if lb["fails"] else "loses" if lb["lost"] else "ok")
    print(f"Rails v7: unconvertible (out of all arms) {len(unconv)}")
    arms, warn = arms_for(ids, E["v7"], F, SE)
    report("Rails v7 A1, 0.1.21 (held-out, PRIMARY)", sorted(ids), arms, warn, T, True)
    sent = sorted(i for i in ids if F[i] is not None)
    a2 = {k: {i: v[i] for i in sent} for k, v in arms.items()}
    report("Rails v7, sent to the model (exploratory)", sent, a2, warn, T, False)
    # P5 (dev: the v3 184 under 0.1.21; sensitivity only)
    labs = {r["id"]: r for r in map(json.loads, open(os.path.join(L.R7, "p5", "data", "labels_v3.jsonl")))}
    stm = {}
    for p in glob.glob(os.path.join(SP, "p2", "data", "items_p2", "*.jsonl")):
        for l in open(p):
            x = json.loads(l); stm[x["id"]] = x["raw"]["statements"]
    items = {r["id"]: r for r in L.p5_items()}
    ids, F, SE, T, unconv = [], {}, {}, {}, []
    for k, lb in labs.items():
        if not lb.get("state_same", True):
            continue
        f = None
        if not lb["decided"]:
            try:
                f = L.p5_facts(items[k], stm[k])
            except C.Unconvertible:
                unconv.append(k); continue
        ids.append(k); F[k] = f; SE[k] = bool(lb["schema_error"])
        lp = lb["label_product"]
        T[k] = (bool(lp["fails"] or lp["lost"]), "fails" if lp["fails"] else "loses" if lp["lost"] else "ok")
    print(f"\nP5: unconvertible {len(unconv)}")
    arms, warn = arms_for(ids, E["p5"], F, SE)
    report("P5: v3 184 under 0.1.21 (DEV, sensitivity only)", sorted(ids), arms, warn, T, True)


if __name__ == "__main__":
    main()
