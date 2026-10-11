"""Recomputes the v3 product evaluation (PREREG_v3, section 4) from answers_v3.jsonl. The product's verdict and reason
were computed with ekbasis.migrations.FileVerdict at commit b18bb43 (frozen/analysis_v3.py); this script recomputes the
metrics from them. Standard library only; writes recompute_v3_output.txt."""
import io, json, math, os, sys
from contextlib import redirect_stdout
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "frozen"))
import analysis as A  # noqa: E402  (the study's bootstrap)


def wilson(k, n, z=1.96):
    p, d = k / n, 1 + z * z / n
    c, h = p + z * z / (2 * n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def binom(b, c):
    n, k = b + c, min(b, c)
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def ok_kind(p, t):
    return {"fails": "fails", "schema": "fails", "loses": "loses"}.get(p) == t


def main():
    R = [json.loads(l) for l in open(os.path.join(HERE, "answers_v3.jsonl"))]
    tr = [r["truth"]["risky"] for r in R]
    for who in ("rules", "product"):
        v = [r[who]["risky"] for r in R]
        acc = sum(a == b for a, b in zip(tr, v)) / len(R)
        both = [r for r in R if r["truth"]["risky"] and r[who]["risky"]]
        ben = [r for r in R if not r["truth"]["risky"]]
        print(f"{who:<8} accuracy {acc:.3f} recall {len(both) / sum(tr):.3f} reason exact "
              f"{sum(ok_kind(r[who]['kind'], r['truth']['kind']) for r in both) / len(both):.3f} (n={len(both)}) "
              f"false alarms on benign {sum(r[who]['risky'] for r in ben) / len(ben):.3f} ({len(ben)})")
    pv, rv = [r["product"]["risky"] for r in R], [r["rules"]["risky"] for r in R]
    acc = sum(a == b for a, b in zip(tr, pv)) / len(R)
    ci = A.boot(lambda idx: sum(tr[i] == pv[i] for i in idx) / len(idx), len(R))
    d = lambda idx: (sum(tr[i] == pv[i] for i in idx) - sum(tr[i] == rv[i] for i in idx)) / len(idx)
    cd = A.boot(d, len(R))
    print(f"P1 accuracy {acc:.3f} [{ci[0]:.3f},{ci[1]:.3f}], minus rules {d(range(len(R))):+.3f} [{cd[0]:+.3f},{cd[1]:+.3f}]"
          f" -> {'PASS' if acc >= 0.85 and ci[0] >= 0.80 and cd[0] > 0 else 'FAIL'}")
    both = [r for r in R if r["truth"]["risky"] and r["product"]["risky"]]
    k = sum(ok_kind(r["product"]["kind"], r["truth"]["kind"]) for r in both)
    w = wilson(k, len(both))
    print(f"P2 reason exact {k}/{len(both)} [{w[0]:.3f},{w[1]:.3f}] -> {'PASS' if k / len(both) >= 0.85 and w[0] >= 0.75 else 'FAIL'}")
    ben = [r for r in R if not r["truth"]["risky"]]
    n = sum(r["product"]["risky"] for r in ben)
    w = wilson(n, len(ben))
    b = sum(1 for r in ben if r["rules"]["risky"] and not r["product"]["risky"])
    c = sum(1 for r in ben if r["product"]["risky"] and not r["rules"]["risky"])
    fr = sum(r["rules"]["risky"] for r in ben) / len(ben)
    print(f"P3 false alarms {n}/{len(ben)} [{w[0]:.3f},{w[1]:.3f}], rules {fr:.3f}, McNemar p={binom(b, c):.4f} -> "
          f"{'PASS' if n / len(ben) <= 0.20 and w[1] <= 0.30 and n / len(ben) < fr and binom(b, c) < 0.05 else 'FAIL'}")
    rec = len(both) / sum(tr)
    print(f"P4 recall {rec:.3f} -> {'PASS' if rec >= 0.85 else 'FAIL'}")


if __name__ == "__main__":
    buf = io.StringIO()
    with redirect_stdout(buf):
        main()
    print(buf.getvalue())
    open(os.path.join(HERE, "recompute_v3_output.txt"), "w").write(buf.getvalue())
