"""The pre-registered analysis. python analyze.py dev|test [tag]"""
from __future__ import annotations

import json
import os
import random
import sys

from common import THRESHOLD, lint
from scenarios import SCENARIOS

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 20261011
BOOT = 10000


def f1(y, yhat):
    tp = sum(a and b for a, b in zip(y, yhat))
    fp = sum((not a) and b for a, b in zip(y, yhat))
    fn = sum(a and not b for a, b in zip(y, yhat))
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def conf(y, yhat):
    tp = sum(a and b for a, b in zip(y, yhat))
    fp = sum((not a) and b for a, b in zip(y, yhat))
    fn = sum(a and not b for a, b in zip(y, yhat))
    tn = sum((not a) and (not b) for a, b in zip(y, yhat))
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    mcc_d = ((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)) ** 0.5
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(p, 3), "recall": round(r, 3),
            "f1": round(f1(y, yhat), 3), "mcc": round((tp * tn - fp * fn) / mcc_d, 3) if mcc_d else 0.0,
            "false_alarm": round(fp / (fp + tn), 3) if fp + tn else None}


def auroc(y, s):
    pos = [b for a, b in zip(y, s) if a]
    neg = [b for a, b in zip(y, s) if not a]
    if not pos or not neg:
        return None
    w = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(w / (len(pos) * len(neg)), 3)


def boot_f1_diff(y, a, b):
    rng = random.Random(SEED)
    n, d = len(y), []
    for _ in range(BOOT):
        idx = [rng.randrange(n) for _ in range(n)]
        yy = [y[i] for i in idx]
        d.append(f1(yy, [a[i] for i in idx]) - f1(yy, [b[i] for i in idx]))
    d.sort()
    return round(d[int(0.025 * BOOT)], 3), round(d[int(0.975 * BOOT)], 3)


def main():
    split = sys.argv[1]
    tag = ("_" + sys.argv[2]) if len(sys.argv) > 2 else ""
    ids = json.load(open(os.path.join(HERE, "split.json")))[split]
    labels = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(HERE, "labels.jsonl"))}
    answers = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(HERE, f"answers_{split}{tag}.jsonl"))}
    items = {s["id"]: s for s in SCENARIOS}
    exclude = set(filter(None, os.environ.get("EXCLUDE", "").split(",")))  # sensitivity: EXCLUDE=D04
    ids = [i for i in ids if i in answers and i not in exclude]
    y = [labels[i]["harmful"] for i in ids]
    score = [max(answers[i]["p"].values()) for i in ids]
    ek = [s >= THRESHOLD for s in score]
    li = [bool(lint(items[i]["sql"])) for i in ids]
    union = [a or b for a, b in zip(ek, li)]
    res = {"n": len(ids), "harmful": sum(y), "benign": len(y) - sum(y),
           "ekbasis": conf(y, ek), "linter": conf(y, li), "union": conf(y, union),
           "auroc_ekbasis_max_p": auroc(y, score), "auroc_linter": auroc(y, [float(x) for x in li]),
           "f1_diff_ekbasis_minus_linter": round(f1(y, ek) - f1(y, li), 3),
           "f1_diff_ci95": boot_f1_diff(y, ek, li),
           "f1_diff_union_minus_linter": round(f1(y, union) - f1(y, li), 3),
           "f1_diff_union_ci95": boot_f1_diff(y, union, li)}
    blind = [k for k, i in enumerate(ids) if y[k] and not li[k]]
    res["blind_harmful"] = {"n": len(blind), "ekbasis_caught": sum(ek[k] for k in blind),
                            "ids": [ids[k] for k in blind], "caught_ids": [ids[k] for k in blind if ek[k]]}
    ben = [k for k in range(len(ids)) if not y[k]]
    res["benign_false_alarms"] = {"ekbasis": [ids[k] for k in ben if ek[k]], "linter": [ids[k] for k in ben if li[k]]}
    res["missed_by_ekbasis"] = [ids[k] for k in range(len(ids)) if y[k] and not ek[k]]
    per_q = {}
    for q, lab in (("beyond", "lost"), ("fail", "failed"), ("lock", "lock")):
        yy = [labels[i][lab] for i in ids]
        ss = [answers[i]["p"][q] for i in ids]
        per_q[q] = {"label": lab, "positives": sum(yy), "auroc": auroc(yy, ss),
                    **conf(yy, [s >= THRESHOLD for s in ss])}
    res["per_question"] = per_q
    res["rows"] = [{"id": i, "design": items[i]["design"], "lost": labels[i]["lost"], "failed": labels[i]["failed"],
                    "lock": labels[i]["lock"], "lint": li[k], **{"p_" + q: round(v, 3) for q, v in answers[i]["p"].items()}}
                   for k, i in enumerate(ids)]
    out = os.path.join(HERE, f"results_{split}{tag}" + ("_excl_" + "_".join(sorted(exclude)) if exclude else "") + ".json")
    json.dump(res, open(out, "w"), indent=1)
    show = {k: v for k, v in res.items() if k != "rows"}
    print(json.dumps(show, indent=1))
    for r in res["rows"]:
        print(r)


if __name__ == "__main__":
    main()
