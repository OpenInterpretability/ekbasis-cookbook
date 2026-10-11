"""read_once parity: SEP (read_once=False, today's guard) vs ONCE (read_once=True) on the 184 v3 migrations, regimes N
and R, hosted API, concurrency 1, arms interleaved per item in a seeded random order. Resumable.

    python run.py --go            # writes ans/answers.jsonl (one line per item x regime x arm)
"""
import json, os, random, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "ekbasis"))
from ekbasis.client import CannotJudge, Ekbasis
from ekbasis import migrations as M

V4 = os.path.join(HERE, "..", "v4")
OUT = os.path.join(HERE, "ans", "answers.jsonl")
SEED = 20261011
SURFACE = "read-once-parity"


def load_requests():
    allowed = {"lost": M.Q_LOST, "fails": M.Q_FAILS, "half": M.Q_HALF}
    jobs = []
    for reg in ("N", "R"):
        for line in open(os.path.join(V4, "st", f"req_t2_old.{reg}.jsonl")):
            r = json.loads(line)
            for k, q in r["questions"].items():   # the product's questions, word for word
                assert q == allowed[k], (r["id"], k)
            jobs.append({"id": r["id"], "regime": reg, "state": r["state"], "questions": r["questions"]})
    return jobs


def main():
    if "--go" not in sys.argv:
        sys.exit("refusing to call the model without --go")
    jobs = load_requests()
    rng = random.Random(SEED)
    rng.shuffle(jobs)
    for j in jobs:
        j["order"] = ["sep", "once"] if rng.random() < 0.5 else ["once", "sep"]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT):
            d = json.loads(l)
            if "error" not in d:
                done.add((d["id"], d["regime"], d["arm"]))
    key = open(os.path.expanduser("~/.config/ekbasis/study_api_key")).read().strip()
    c = Ekbasis(url="https://openinterp.org/api/v1", api_key=key, timeout=300, surface=SURFACE)
    with open(OUT, "a") as f:
        for n, j in enumerate(jobs):
            for arm in j["order"]:
                if (j["id"], j["regime"], arm) in done:
                    continue
                rec, tries, err = None, 0, None
                while rec is None and tries < 3:
                    t0 = time.time()
                    try:
                        a = c.ask(j["state"], j["questions"], read_once=(arm == "once"))
                        rec = {"id": j["id"], "regime": j["regime"], "arm": arm, "secs": round(time.time() - t0, 3),
                               "timing": c.last_timing, "usage": c.last_usage, "request_id": c.last_request_id,
                               "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                               **{f"p_{k}": a[k].p_yes for k in j["questions"]}}
                    except CannotJudge as e:
                        err = str(e)[:300]
                        if c.last_status == 429:          # quota/rate: wait, does not count as a try
                            time.sleep(30)
                            continue
                        tries += 1
                        time.sleep(10 * tries)
                if rec is None:
                    rec = {"id": j["id"], "regime": j["regime"], "arm": arm, "error": err,
                           "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                f.write(json.dumps(rec) + "\n")
                f.flush()
                print(n, j["regime"], arm, j["id"], rec.get("error") or
                      {k: round(v, 3) for k, v in rec.items() if k.startswith("p_")}, rec.get("usage"), flush=True)


if __name__ == "__main__":
    main()
