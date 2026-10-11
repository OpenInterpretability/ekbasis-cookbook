"""T2, passo 3: chama a API hospedada para os estados que precisam do modelo. Concorrência 2, ordem embaralhada com
semente 20261011 (braços e regimes intercalados), até 6 tentativas com espera crescente em 429/5xx/erro de rede.
Retomável: chaves já respondidas em OUT são puladas. NEW com estado idêntico ao OLD não é chamado (herda).
    python3 ask_t2.py OUT.jsonl --go"""
import json, os, random, sys, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = "https://openinterp.org/api/v1"
KEY = open(os.path.expanduser("~/.config/ekbasis/study_api_key")).read().strip()
out_path = sys.argv[1]
if "--go" not in sys.argv:
    sys.exit("refusing to call the model without --go")


def load(p):
    return {json.loads(l)["id"]: json.loads(l) for l in open(p)}


jobs = []
for reg in "RN":
    O, N = load(f"data/st_old.{reg}.jsonl"), load(f"data/st_new.{reg}.jsonl")
    for i in O:
        if O[i]["questions"]:
            jobs.append(("old", reg, i, O[i]))
        if N[i]["questions"] and not (N[i]["state"] == O[i]["state"]):
            jobs.append(("new", reg, i, N[i]))
random.Random(20261011).shuffle(jobs)
done = set()
if os.path.exists(out_path):
    for l in open(out_path):
        r = json.loads(l)
        if "error" not in r:
            done.add((r["arm"], r["regime"], r["id"]))
todo = [j for j in jobs if (j[0], j[1], j[2]) not in done]
print(f"jobs {len(jobs)}, done {len(done)}, to do {len(todo)}", flush=True)
lock = threading.Lock()


def call(job):
    arm, reg, i, st = job
    err = None
    for attempt in range(6):
        t0 = time.time()
        req = urllib.request.Request(f"{URL}/v1/systemone", method="POST",
                                     data=json.dumps({"state": st["state"], "questions": st["questions"]}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "ekbasis-study-corte",
                                              "Authorization": f"Bearer {KEY}", "X-Ekbasis-Surface": "corte-schema-t2"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read())
                rec = {"arm": arm, "regime": reg, "id": i, "secs": round(time.time() - t0, 2),
                       "server_timing": r.headers.get("Server-Timing"), "request_id": r.headers.get("X-Ekbasis-Request-Id"),
                       "usage": d.get("usage"), "chars": len(st["state"]),
                       **{f"p_{k}": float(v["probability"]) for k, v in d["answers"].items()}}
            break
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            err = f"{type(e).__name__}: {e}"[:300]
        time.sleep(min(120, 10 * 2 ** attempt))
    else:
        rec = None
    if rec is None:
        rec = {"arm": arm, "regime": reg, "id": i, "error": err}
    with lock:
        with open(out_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(arm, reg, i[:50], rec.get("error") or (round(rec["p_lost"], 3), round(rec["p_fails"], 3), rec["secs"]), flush=True)


with ThreadPoolExecutor(2) as ex:
    list(ex.map(call, todo))
