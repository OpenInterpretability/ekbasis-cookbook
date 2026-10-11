"""Recomputes every table of this study from the released answers. Optionally re-downloads the migrations and re-runs
the whole pipeline.

    python recompute.py                 # seconds; standard library only; writes recompute_output.txt
    python recompute.py --check-sources # also clones the 12 repos at the pinned commits (sparse, shallow) and checks
                                        # that every migration file hashes like the one that ran, and that the frozen
                                        # sampler draws the same 599 ids
    python recompute.py --execute       # also re-executes the sampled migrations on a local PostgreSQL 16 listening
                                        # on 127.0.0.1:55491 (user postgres, trust) and compares the labels
                                        # (needs: pip install "psycopg[binary]"; about 5 minutes on a laptop)

The migrations are not redistributed: --check-sources downloads them from their repositories.
The metric functions come unchanged from frozen/analysis.py.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = os.path.join(HERE, "frozen")
sys.path.insert(0, FROZEN)
import analysis as A  # noqa: E402  (frozen; only its metric functions are used here)

TASKS = {"lost": "lost", "fails": "fails", "half": "half_applied"}


def load():
    return [json.loads(l) for l in open(os.path.join(HERE, "answers.jsonl"))]


def ev(rows, score, task, name):
    y = [r["label"][TASKS[task]] for r in rows]
    s = [score(r) for r in rows]
    p, rc, f = A.prf(y, [x >= 0.5 for x in s])
    a = A.auroc(y, s)
    ci = A.boot(lambda idx: A.auroc([y[i] for i in idx], [s[i] for i in idx]), len(y))
    cf = A.boot(lambda idx: A.prf([y[i] for i in idx], [s[i] >= 0.5 for i in idx])[2], len(y))
    print(f"{name:<34} n={len(y):3d} pos={sum(y):3d}  AUROC {a:.3f} [{ci[0]:.3f},{ci[1]:.3f}]  P {p:.3f} R {rc:.3f} "
          f"F1 {f:.3f} [{cf[0]:.3f},{cf[1]:.3f}]  ECE {A.ece(y, s):.3f}")
    return y, s


def dF1(rows, s1, s2, task):
    y = [r["label"][TASKS[task]] for r in rows]
    a = [s1(r) for r in rows]
    b = [s2(r) for r in rows]
    d = lambda idx: (A.prf([y[i] for i in idx], [a[i] >= 0.5 for i in idx])[2] -
                     A.prf([y[i] for i in idx], [b[i] >= 0.5 for i in idx])[2])
    return d(range(len(y))), A.boot(d, len(y))


def tables(rows):
    print(f"items {len(rows)}; lost {sum(r['label']['lost'] for r in rows)}, fails {sum(r['label']['fails'] for r in rows)}, "
          f"half_applied {sum(r['label']['half_applied'] for r in rows)}")
    for st in "ABC":
        s = [r for r in rows if r["stratum"] == st]
        print(f"  stratum {st}: n={len(s)} lost={sum(r['label']['lost'] for r in s)} fails={sum(r['label']['fails'] for r in s)} "
              f"half={sum(r['label']['half_applied'] for r in s)}")
    A_ = [r for r in rows if r["stratum"] == "A"]
    ek = lambda t: (lambda r: r["ekbasis"][t])
    rule = lambda nm: (lambda r: float(r["rules"][nm]))

    print("\n== Registered analysis (PREREG 5.3)")
    y, s = ev(A_, ek("lost"), "lost", "H1 lost, stratum A, Ekbasis")
    cl = A.cluster_boot(lambda idx: A.auroc([y[i] for i in idx], [s[i] for i in idx]), [r["repo"] for r in A_])
    a = A.auroc(y, s)
    ci = A.boot(lambda idx: A.auroc([y[i] for i in idx], [s[i] for i in idx]), len(y))
    print(f"   repo-cluster CI [{cl[0]:.3f},{cl[1]:.3f}] -> H1 {'PASS' if a >= 0.85 and ci[0] >= 0.80 else 'FAIL'}")
    d, c = dF1(A_, ek("lost"), rule("R3"), "lost")
    print(f"H2 F1(Ekbasis) - F1(R3), stratum A: {d:+.3f} [{c[0]:+.3f},{c[1]:+.3f}] -> {'PASS' if c[0] > 0 else 'FAIL'}")
    y3, s3 = ev(rows, ek("fails"), "fails", "H3 fails, all, Ekbasis")
    a3 = A.auroc(y3, s3)
    ci3 = A.boot(lambda idx: A.auroc([y3[i] for i in idx], [s3[i] for i in idx]), len(y3))
    d3, c3 = dF1(rows, ek("fails"), rule("F1"), "fails")
    print(f"   F1(Ekbasis) - F1(rule F1): {d3:+.3f} [{c3[0]:+.3f},{c3[1]:+.3f}] -> H3 "
          f"{'PASS' if a3 >= 0.80 and ci3[0] >= 0.70 and c3[0] > 0 else 'FAIL'}")
    ev(rows, ek("half"), "half", "H4 half applied, all (exploratory)")
    print(f"H5 ECE lost, stratum A: {A.ece(y, s):.3f} -> {'PASS' if A.ece(y, s) <= 0.10 else 'FAIL'}")

    print("\n== Rules (no model)")
    for nm, task in (("R1", "lost"), ("R2", "lost"), ("R3", "lost")):
        ev(A_, rule(nm), task, f"{nm} lost, stratum A")
    ev(rows, rule("F1"), "fails", "F1 fails, all")
    ev(rows, rule("H1"), "half", "H1 half applied, all")

    print("\n== Secondary and sensitivity (PREREG 5.4)")
    for nm, keep in (("S1 no partial-copy-only losses", lambda r: not (r["label"]["lost"] and r["mechanisms"] == ["partial_copy"])),
                     ("S2 no synthetic-cast failures", lambda r: not r["synthetic_cast"])):
        sub = [r for r in rows if keep(r)]
        subA = [r for r in sub if r["stratum"] == "A"]
        ev(subA, ek("lost"), "lost", f"{nm}: lost, A")
        d, c = dF1(subA, ek("lost"), rule("R3"), "lost")
        print(f"   F1(Ekbasis) - F1(R3): {d:+.3f} [{c[0]:+.3f},{c[1]:+.3f}]")
        ev(sub, ek("fails"), "fails", f"{nm}: fails, all")
    for t in ("lost", "fails"):
        yt = [r["label_tx"][t] for r in rows]
        st_ = [r["ekbasis"][t] for r in rows]
        p, rc, f = A.prf(yt, [x >= 0.5 for x in st_])
        print(f"transactional runner labels, {t}: pos={sum(yt)} AUROC {A.auroc(yt, st_):.3f} P {p:.3f} R {rc:.3f} F1 {f:.3f}")
    yA = [r["label"]["lost"] for r in A_]
    sA = [r["ekbasis"]["lost"] for r in A_]
    rA = [float(r["rules"]["R3"]) for r in A_]
    rr = A.prf(yA, [x >= 0.5 for x in rA])
    thr = max((t for t in sorted(set(sA), reverse=True) if A.prf(yA, [x >= t for x in sA])[1] >= rr[1]), default=0.0)
    pm = A.prf(yA, [x >= thr for x in sA])
    print(f"at R3's recall {rr[1]:.3f} (stratum A): R3 precision {rr[0]:.3f}, Ekbasis precision {pm[0]:.3f} (threshold {thr:.3f})")
    two = A.prf(yA, [a >= 0.5 and b >= 0.5 for a, b in zip(rA, sA)])
    print(f"two-stage R3 AND Ekbasis (stratum A): P {two[0]:.3f} R {two[1]:.3f} F1 {two[2]:.3f}")

    print("\n== Error analysis (exploratory, after the run)")
    for nm, keep in (("migrations that fail", True), ("migrations that run cleanly", False)):
        ev([r for r in A_ if r["label"]["fails"] == keep], ek("lost"), "lost", f"lost, A, {nm}")
    fp = [r for r in A_ if not r["label"]["lost"] and r["ekbasis"]["lost"] >= 0.5]
    print(f"false alarms on lost (stratum A): {len(fp)}, of which in failing migrations: {sum(r['label']['fails'] for r in fp)}")

    g = [r for r in rows if r.get("glm") and all(v is not None for v in r["glm"].values())]
    if g:
        print(f"\n== Exploratory: the same {len(g)} items, Ekbasis vs GLM vs rules")
        for t, rn in (("lost", "R3"), ("fails", "F1"), ("half", "H1")):
            ev(g, ek(t), t, f"{t}: Ekbasis")
            ev(g, lambda r, t=t: r["glm"][t], t, f"{t}: GLM")
            ev(g, rule(rn), t, f"{t}: rule {rn}")
            yy = [r["label"][TASKS[t]] for r in g]
            e_ = [r["ekbasis"][t] for r in g]
            m_ = [r["glm"][t] for r in g]
            dd = lambda idx: A.auroc([yy[i] for i in idx], [e_[i] for i in idx]) - A.auroc([yy[i] for i in idx], [m_[i] for i in idx])
            c = A.boot(dd, len(g))
            print(f"   AUROC(Ekbasis) - AUROC(GLM): {dd(range(len(g))):+.3f} [{c[0]:+.3f},{c[1]:+.3f}]")
            d, c = dF1(g, ek(t), lambda r, t=t: r["glm"][t], t)
            print(f"   F1(Ekbasis) - F1(GLM): {d:+.3f} [{c[0]:+.3f},{c[1]:+.3f}]")


def check_sources(rows, execute):
    excl = [json.loads(l) for l in open(os.path.join(HERE, "excluded.jsonl"))]
    allrec = rows + excl
    tmp = tempfile.mkdtemp(prefix="migstudy_")
    sys.path.insert(0, FROZEN)
    import frame as F
    F.R = os.path.join(tmp, "repos")
    os.makedirs(F.R)
    for name, (repo, layout, sub) in F.SOURCES.items():
        commit = next(r["commit"] for r in allrec if r["repo"] == name)
        d = os.path.join(F.R, name)
        subprocess.run(["git", "init", "-q", d], check=True)
        subprocess.run(["git", "-C", d, "remote", "add", "origin", f"https://github.com/{repo}"], check=True)
        subprocess.run(["git", "-C", d, "sparse-checkout", "set", "--no-cone", f"/{sub}/"], check=True)
        subprocess.run(["git", "-C", d, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", commit], check=True)
        subprocess.run(["git", "-C", d, "checkout", "-q", "FETCH_HEAD"], check=True)
    bad = 0
    import hashlib
    for r in allrec:
        p = os.path.join(F.R, r["repo"], r["path"])
        h = hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None
        bad += h != r["file_sha256"]
    print(f"\n== Sources: {len(allrec)} sampled files, {bad} with a different hash")
    F.ROOT = tmp
    with redirect_stdout(io.StringIO()):
        F.main()
    drawn = {f"{json.loads(l)['repo']}/{json.loads(l)['mig']}" for l in open(os.path.join(tmp, "data", "sample.jsonl"))}
    print(f"frozen sampler: {len(drawn)} ids drawn, identical to the released ones: {drawn == {r['id'] for r in allrec}}")
    if execute:
        import build as Bd
        Bd.R, Bd.ROOT = F.R, tmp
        os.makedirs(os.path.join(tmp, "data", "items"), exist_ok=True)
        for name in F.SOURCES:
            Bd.process(name)
        got = {}
        for name in F.SOURCES:
            for l in open(os.path.join(tmp, "data", "items", f"{name}.jsonl")):
                it = json.loads(l)
                got[f"{name}/{it['mig']}"] = it
        same = sum(1 for r in rows if not got[r["id"]].get("excluded") and
                   all(got[r["id"]]["label"][k] == r["label"][k] for k in ("lost", "fails", "half_applied")))
        print(f"re-executed: {same} of {len(rows)} items get the same three labels (the run that was scored got 580 of "
              f"582 in an independent rebuild; see README, Limits)")


def main():
    rows = load()
    buf = io.StringIO()
    with redirect_stdout(buf):
        tables(rows)
        if "--check-sources" in sys.argv or "--execute" in sys.argv:
            check_sources(rows, "--execute" in sys.argv)
    out = buf.getvalue()
    print(out)
    open(os.path.join(HERE, "recompute_output.txt"), "w").write(out)


if __name__ == "__main__":
    main()
