"""Fronts 1 and 2: every static item under every pre-registered condition, at concurrency 1, resumable.

Conditions (PREREG.md):
- front 1 (items with "f1"): shield True/False x checker_text keep/remove. "flag" (M2) needs no call: it is the keep
  answer plus the code rule, computed in analyze.py.
- front 2 (items with "f2", and replay_items.jsonl): shield True, delegation False/True.
Identical states are asked once (cache by sha256 of state + question). Answers: answers.jsonl (one line per item x
condition), calls.jsonl (one line per distinct state actually sent). On an HTTP error (429, 5xx, timeout) it waits and
retries; it never prints the key.

usage: run_static.py items.jsonl replay_items.jsonl out_dir [--limit N]
"""
import hashlib
import json
import sys
import time
from pathlib import Path

from ekbasis.client import CannotJudge, Ekbasis
from ekbasis.intent import intent_check


class CachingClient(Ekbasis):
    def __init__(self, calls_path: Path):
        super().__init__(surface="intent-check")
        self.calls_path = calls_path
        self.cache = {}
        if calls_path.exists():
            for l in calls_path.open():
                d = json.loads(l)
                self.cache[d["key"]] = d["p"]
        self.sent = 0

    def ask(self, state, questions, **kw):
        key = hashlib.sha256((state + json.dumps(questions, sort_keys=True)).encode()).hexdigest()
        if key not in self.cache:
            for attempt in range(40):
                try:
                    t0 = time.time()
                    ans = super().ask(state, questions)
                    break
                except CannotJudge as e:
                    wait = min(30 * (attempt + 1), 300)
                    print(f"  retry {attempt + 1} in {wait}s: {str(e)[:80]}", flush=True)
                    time.sleep(wait)
            else:
                raise SystemExit("Ekbasis did not answer after 40 attempts")
            p = ans["third_party"].p_yes
            self.cache[key] = p
            self.sent += 1
            with self.calls_path.open("a") as f:
                f.write(json.dumps({"key": key, "p": p, "latency_s": round(time.time() - t0, 3),
                                    "usage": self.last_usage, "t": time.time()}) + "\n")
        p = self.cache[key]

        class A:
            p_yes = p
        return {"third_party": A}


def conditions(item):
    out = []
    if "f1" in item.get("fronts", []):
        for shield in (True, False):
            for ct in ("keep", "remove"):
                out.append({"front": "f1", "shield": shield, "checker_text": ct, "delegation": False})
    if "f2" in item.get("fronts", []) or item.get("kind") == "recorded":
        for dele in (False, True):
            out.append({"front": "f2", "shield": True, "checker_text": "keep", "delegation": dele})
    return out


def main():
    items_path, replay_path, out_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    out_dir.mkdir(parents=True, exist_ok=True)
    items = [json.loads(l) for l in open(items_path)] + [json.loads(l) for l in open(replay_path)]
    if limit:
        items = items[:limit]
    ans_path = out_dir / "answers.jsonl"
    done = set()
    if ans_path.exists():
        for l in ans_path.open():
            d = json.loads(l)
            done.add((str(d["id"]), d["front"], d["shield"], d["checker_text"], d["delegation"]))
    client = CachingClient(out_dir / "calls.jsonl")
    t_start = time.time()
    for n, it in enumerate(items):
        for c in conditions(it):
            k = (str(it["id"]), c["front"], c["shield"], c["checker_text"], c["delegation"])
            if k in done:
                continue
            v = intent_check(it["request"], it["events"], it["action"], client=client, shield=c["shield"],
                             checker_text=c["checker_text"], delegation=c["delegation"])
            with ans_path.open("a") as f:
                f.write(json.dumps({"id": it["id"], **c, "suite": it["suite"], "ut": it["ut"], "it": it["it"],
                                    "attack": it.get("attack", "recorded"), "kind": it["kind"], "p": v.p,
                                    "verdict": v.verdict, "addressed_checker": v.addressed_checker,
                                    "delegated": list(v.delegated), "orig_p": it.get("orig_p")}) + "\n")
        if n % 25 == 0:
            print(f"{n + 1}/{len(items)} items, {client.sent} calls sent, {time.time() - t_start:.0f}s", flush=True)
    print(f"done: {client.sent} calls sent")


if __name__ == "__main__":
    main()
