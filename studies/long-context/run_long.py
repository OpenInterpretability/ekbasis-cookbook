"""Long-context study: ask the hosted API for one request file (PREREG.md section 5). Resumable (ids already answered
in OUT are skipped), study key read from ~/.config/ekbasis/study_api_key and never printed.

    venv/bin/python run_long.py data/req_16k.jsonl ans/16k.jsonl --conc 2 [--ids data/subsample.txt] --go

Budget guard: before each request, the input tokens already used by every ans/*.jsonl plus this request's estimate
(2 x its tokens + 400) must stay <= CAP, otherwise the run stops (loudly). HTTP 429 or 503: wait 60 s and retry, up to
20 times, never more concurrency. Other errors: 3 tries, then the item is recorded with "error".
"""
import argparse, glob, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "ekbasis"))
from ekbasis.client import CannotJudge, Ekbasis   # noqa: E402

URL = "https://openinterp.org/api/v1"
KEY_PATH = os.path.expanduser("~/.config/ekbasis/study_api_key")
CAP = int(os.environ.get("CTX_CAP", 50_000_000))
LOCK = threading.Lock()


def used():
    n = 0
    for p in glob.glob(os.path.join(HERE, "ans", "*.jsonl")):
        for l in open(p):
            r = json.loads(l)
            n += (r.get("usage") or {}).get("input_tokens") or 0
            n += r.get("tokens_failed", 0)
    return n


def ask_one(it, key, surface, out):
    c = Ekbasis(URL, key, timeout=600, surface=surface)
    err, waits = None, 0
    tries = 0
    while tries < 3:
        t0 = time.time()
        try:
            a = c.ask(it["state"], it["questions"])
            rec = {"id": it["id"], "cond": it.get("cond"), "depth": it.get("depth"), "secs": round(time.time() - t0, 2),
                   "timing": c.last_timing, "request_id": c.last_request_id, "usage": c.last_usage,
                   **{f"p_{k}": v.p_yes for k, v in a.items()}, "t_end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            break
        except CannotJudge as e:
            err = str(e)[:300]
            if c.last_status in (429, 503) and waits < 20:
                waits += 1
                time.sleep(60)
                continue
            tries += 1
            time.sleep(10 * tries)
    else:
        rec = {"id": it["id"], "cond": it.get("cond"), "error": err, "status": c.last_status}
    with LOCK:
        out.write(json.dumps(rec) + "\n")
        out.flush()
    print(it["id"], rec.get("error") or {k: round(v, 3) for k, v in rec.items() if k.startswith("p_")},
          rec.get("secs"), (rec.get("usage") or {}).get("input_tokens"), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("requests")
    ap.add_argument("out")
    ap.add_argument("--conc", type=int, default=1)
    ap.add_argument("--ids", help="ids to ask, in this order")
    ap.add_argument("--surface", default="study-context-length")
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    if not a.go:
        sys.exit("refusing to call the model without --go")
    if a.conc > 2:
        sys.exit("concurrency above 2 is not allowed (PREREG section 5)")
    key = open(KEY_PATH).read().strip()
    items = [json.loads(l) for l in open(a.requests)]
    if a.ids:
        order = open(a.ids).read().split()          # the run follows this file's order
        by = {i["id"]: i for i in items}
        items = [by[k] for k in order if k in by]
    biggest = max(len(i["state"]) for i in items)
    if biggest > 200_000 and a.conc != 1:   # DEVIATIONS D1: was 90_000 chars, which refused the 32k states
        sys.exit("states of 64k tokens and more run at concurrency 1")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)["id"] for l in open(a.out) if "error" not in json.loads(l)}
    todo = [i for i in items if i["id"] not in done]
    print(f"{len(todo)} to ask, {len(done)} done; used so far {used():,} of {CAP:,}", flush=True)
    with open(a.out, "a") as f, ThreadPoolExecutor(a.conc) as ex:
        futs = []
        for it in todo:
            est = 2 * it.get("tokens", int(len(it["state"]) / 1.6)) + 400
            while len([x for x in futs if not x.done()]) >= a.conc:
                time.sleep(0.2)
            if used() + est * a.conc > CAP:
                print(f"BUDGET STOP: used {used():,} + {est:,} > {CAP:,}", flush=True)
                break
            futs.append(ex.submit(ask_one, it, key, a.surface, f))
        for x in futs:
            x.result()
    print(f"used {used():,} of {CAP:,}", flush=True)


if __name__ == "__main__":
    main()
