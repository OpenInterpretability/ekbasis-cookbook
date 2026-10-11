"""Framework eval v4, step 3: ask Ekbasis (hosted API, concurrency 1). One request per item , the frozen state and
questions. Records Server-Timing (gateway queue vs model). Resumable.

    python run_v2.py --go [--pilot 10]
"""
import argparse, json, os, sys, time, urllib.error, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "mgfw"))
from ekbasis.client import USER_AGENT, Answer

URL = "https://openinterp.org/api/v1"
KEY_PATH = os.path.expanduser("~/.config/ekbasis/study_api_key")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--arm", default="v3")
    ap.add_argument("--pilot", type=int, default=0)
    a = ap.parse_args()
    if not a.go:
        sys.exit("refusing to call the model without --go")
    key = open(KEY_PATH).read().strip()
    items = [json.loads(l) for l in open(os.path.join(HERE, "data", f"requests_v4.jsonl"))]
    if a.pilot:
        items = items[::max(1, len(items) // a.pilot)][:a.pilot]
    os.makedirs(os.path.join(HERE, "preds"), exist_ok=True)
    out = os.path.join(HERE, "preds", "v4.jsonl")
    done = {json.loads(l)["id"] for l in open(out)} if os.path.exists(out) else set()
    with open(out, "a") as f:
        for it in items:
            if it["id"] in done:
                continue
            err = None
            for attempt in range(3):
                t0 = time.time()
                req = urllib.request.Request(f"{URL}/v1/systemone", method="POST",
                                             data=json.dumps({"state": it["state"], "questions": it["questions"]}).encode(),
                                             headers={"Content-Type": "application/json", "User-Agent": USER_AGENT,
                                                      "Authorization": f"Bearer {key}", "X-Ekbasis-Surface": "pr-study-v4"})
                try:
                    with urllib.request.urlopen(req, timeout=300) as r:
                        d = json.loads(r.read())
                        timing, rid = r.headers.get("Server-Timing"), r.headers.get("X-Ekbasis-Request-Id")
                    ans = {k: Answer.from_api(v) for k, v in d["answers"].items()}
                    rec = {"id": it["id"], "secs": round(time.time() - t0, 2), "server_timing": timing, "request_id": rid,
                           "usage": d.get("usage"), **{f"p_{k}": v.p_yes for k, v in ans.items()}}
                    break
                except urllib.error.HTTPError as e:
                    err = f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"
                except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                    err = f"{type(e).__name__}: {e}"[:300]
                time.sleep(5 * (attempt + 1))
            else:
                rec = {"id": it["id"], "error": err}
            f.write(json.dumps(rec) + "\n")
            f.flush()
            print(it["id"], rec.get("error") or {k: round(v, 3) for k, v in rec.items() if k.startswith("p_")}, flush=True)


if __name__ == "__main__":
    main()
