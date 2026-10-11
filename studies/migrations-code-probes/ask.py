"""v4: ask the hosted API for a file of requests ({"id", "state", "questions"}), concurrency 1, study key, Server-Timing
recorded, up to 3 tries. Resumable (ids already in OUT are skipped).

    python ask.py REQUESTS.jsonl OUT.jsonl --surface pr-study-v4-dev --go
"""
import argparse, json, os, sys, time, urllib.error, urllib.request

URL = "https://openinterp.org/api/v1"
KEY_PATH = os.path.expanduser("~/.config/ekbasis/study_api_key")
UA = "ekbasis-study-v4"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("requests")
    ap.add_argument("out")
    ap.add_argument("--surface", required=True)
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    if not a.go:
        sys.exit("refusing to call the model without --go")
    key = open(KEY_PATH).read().strip()
    items = [json.loads(l) for l in open(a.requests)]
    done = {json.loads(l)["id"] for l in open(a.out)} if os.path.exists(a.out) else set()
    with open(a.out, "a") as f:
        for it in items:
            if it["id"] in done:
                continue
            err = None
            for attempt in range(3):
                t0 = time.time()
                req = urllib.request.Request(f"{URL}/v1/systemone", method="POST",
                                             data=json.dumps({"state": it["state"], "questions": it["questions"]}).encode(),
                                             headers={"Content-Type": "application/json", "User-Agent": UA,
                                                      "Authorization": f"Bearer {key}", "X-Ekbasis-Surface": a.surface})
                try:
                    with urllib.request.urlopen(req, timeout=300) as r:
                        d = json.loads(r.read())
                        timing, rid = r.headers.get("Server-Timing"), r.headers.get("X-Ekbasis-Request-Id")
                    rec = {"id": it["id"], "secs": round(time.time() - t0, 2), "server_timing": timing,
                           "request_id": rid, "usage": d.get("usage"),
                           **{f"p_{k}": float(v["probability"]) for k, v in d["answers"].items()}}
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
