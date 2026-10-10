"""WS-K8S firewall, run before any public number (2026-10-10): are the study's evaluation items in the training lineage
of the Ekbasis build that was evaluated (Ekbasis-27B = w4a5, served as Ekbasis-27B-MLX-4bit)?

Evaluation items checked (everything a forecaster or agent read that we wrote):
  - Phase 1: the 24 task records (setup objects, files, request, paths, intent script), the 24 requests alone, and every
    distinct question text the simulated user received (the command + the facts of the touched objects);
  - Phase 0: the 40 scenarios, the 200 forecaster prompts (items.jsonl) and the 8 pilot tasks.
Training lineage checked (local copies of the public Hugging Face datasets, downloaded 2026-10-10):
  - <user>1/ekbasis-data raw/: ftrain_mixG3 (the V42 file, which holds every earlier stage's file), mined_wide and
    mined_chain (r4a's extra sets), and the validation files the lineage chose its checkpoints by;
  - <user>1/eikos-decisions: every file (the published part of Eikos-27B's training data).
Not checkable here: the 7,423 replay rows withheld from ekbasis-data, the Eikos training rows left out of
eikos-decisions, and the base model's (Qwen3.8-27B) pretraining data.

Checks:
  1. exact: sha256 of each item's whitespace-normalised text against every training row's text, and each Phase 1
     request as a substring of any training row;
  2. near-duplicate: word 13-gram hits (any shared 13-gram) and per-item containment of word 8-grams, both over all
     training rows together and against the single closest row;
  3. domain: training rows that mention Kubernetes at all.
    python3 firewall_lineage_check.py <lineage dir> > firewall_lineage_check.json"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "phase1", "tasks"))
sys.path.insert(0, os.path.join(HERE, "phase1", "harness"))
sys.path.insert(0, os.path.join(HERE, "pilot"))
LIN = sys.argv[1]
WORD = re.compile(r"[a-z0-9]+")
K8S = re.compile(r"\b(kubectl|kubernetes|k8s|statefulsets?|persistentvolume(claim)?s?|configmaps?|endpointslices?|"
                 r"noexecute|replicasets?|daemonsets?|kube-system|cascade=orphan|reclaimpolicy)\b", re.I)


def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)


def text(o):
    return "\n".join(strings(o)).replace("@SFX@", "")


def norm(t):
    return " ".join(t.lower().split())


def grams(t, n):
    w = WORD.findall(t.lower())
    return {hash(" ".join(w[i:i + n])) for i in range(len(w) - n + 1)}


# ------------------------------------------------------------------------------------------------ evaluation items
items = {}
import k8s_tasks as T  # noqa: E402
for r in T.records():
    items[f"p1-task {r['id']}"] = text(r)
    items[f"p1-request {r['id']}"] = r["request"].replace("@SFX@", "")
qs = set()
for f in ("runs_h.jsonl", "runs_s.jsonl", "runs_p.jsonl"):
    for l in open(os.path.join(HERE, "phase1", "results", f)):
        for rep in json.loads(l).get("replies") or []:
            qs.add(rep["question"])
for i, q in enumerate(sorted(qs)):
    items[f"p1-question {i:03d}"] = q
for l in open(os.path.join(HERE, "probe", "data", "scenarios.jsonl")):
    s = json.loads(l)
    items[f"p0-scenario {s['id']}"] = text({k: s[k] for k in ("objects", "command", "files")})
for l in open(os.path.join(HERE, "probe", "data", "items.jsonl")):
    it = json.loads(l)
    items[f"p0-prompt {it['id']} {it['cond']}"] = it.get("prompt") or it.get("state")
import pilot_tasks as PT  # noqa: E402
for t in PT.task_records():
    items[f"p0-pilot {t['id']}"] = text({"setup": t["setup"], "request": t["request"]})

exact = {hashlib.sha256(norm(t).encode()).hexdigest(): k for k, t in items.items()}
requests = {k: norm(t) for k, t in items.items() if k.startswith("p1-request")}
G13, G8 = defaultdict(set), defaultdict(set)
n8 = {}
for k, t in items.items():
    for g in grams(t, 13):
        G13[g].add(k)
    g8 = grams(t, 8)
    n8[k] = len(g8)
    for g in g8:
        G8[g].add(k)

# ------------------------------------------------------------------------------------------------ training lineage
SOURCES = sorted(glob.glob(os.path.join(LIN, "ekbasis-data", "raw", "*.jsonl"))) + \
    sorted(glob.glob(os.path.join(LIN, "eikos-decisions", "**", "*.jsonl"), recursive=True))
SOURCES = [p for p in SOURCES if os.path.basename(p) in ("ftrain_mixG3.jsonl", "mined_wide.jsonl", "mined_chain.jsonl",
                                                          "m3val.jsonl", "fval_git.jsonl", "fval_git2.jsonl", "fval_git3.jsonl")
           or "eikos-decisions" in p]
rows_per_source = {}
exact_hits, request_hits, hits13 = [], [], defaultdict(set)
covered8 = defaultdict(set)
best_row = {}  # item -> (shared 8-grams with one row, source, line)
k8s_rows = Counter()
k8s_examples = []
for p in SOURCES:
    src = os.path.relpath(p, LIN)
    n = 0
    for ln, l in enumerate(open(p)):
        n += 1
        t = text(json.loads(l))
        nt = norm(t)
        h = hashlib.sha256(nt.encode()).hexdigest()
        if h in exact:
            exact_hits.append({"item": exact[h], "source": src, "line": ln})
        for k, rq in requests.items():
            if rq in nt:
                request_hits.append({"item": k, "source": src, "line": ln})
        if K8S.search(t):
            k8s_rows[src] += 1
            if len(k8s_examples) < 40:
                m = K8S.search(t)
                k8s_examples.append({"source": src, "line": ln, "match": m.group(0),
                                     "context": t[max(0, m.start() - 150): m.end() + 150]})
        for g in grams(t, 13):
            for k in G13.get(g, ()):
                hits13[k].add((src, ln))
        shared = Counter()
        for g in grams(t, 8):
            for k in G8.get(g, ()):
                covered8[k].add(g)
                shared[k] += 1
        for k, c in shared.items():
            if c > best_row.get(k, (0,))[0]:
                best_row[k] = (c, src, ln)
    rows_per_source[src] = n

per_item = {}
for k in items:
    c = len(covered8.get(k, ()))
    b = best_row.get(k, (0, None, None))
    per_item[k] = {"grams8": n8[k], "containment8_all_rows": round(c / n8[k], 4) if n8[k] else None,
                   "containment8_best_row": round(b[0] / n8[k], 4) if n8[k] else None, "best_row": [b[1], b[2]],
                   "rows_with_shared_13gram": len(hits13.get(k, ()))}
groups = defaultdict(list)
for k, v in per_item.items():
    groups[k.split()[0]].append(v)
out = {
    "eval_items": len(items), "eval_items_by_group": {g: len(v) for g, v in groups.items()},
    "training_rows_by_source": rows_per_source, "training_rows_total": sum(rows_per_source.values()),
    "exact_item_hits": exact_hits, "p1_request_substring_hits": request_hits,
    "items_with_any_13gram_hit": sorted(k for k in items if hits13.get(k)),
    "max_containment8_all_rows_by_group": {g: max(x["containment8_all_rows"] or 0 for x in v) for g, v in groups.items()},
    "max_containment8_best_row_by_group": {g: max(x["containment8_best_row"] or 0 for x in v) for g, v in groups.items()},
    "items_best_row_containment8_ge_0.5": sorted(k for k, v in per_item.items() if (v["containment8_best_row"] or 0) >= 0.5),
    "kubernetes_mentions_by_source": dict(k8s_rows), "kubernetes_mention_examples": k8s_examples,
    "top10_items_by_best_row_containment8": sorted(per_item.items(), key=lambda kv: -(kv[1]["containment8_best_row"] or 0))[:10],
}
print(json.dumps(out, indent=1))
