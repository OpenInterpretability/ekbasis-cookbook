"""GLM-5.3-Flash as judge on the 0.1.19 migration states (see PREREG.md). Resumable: skips ids already in the output."""
import json, os, re, sys, time, urllib.request, concurrent.futures as cf
SC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = sys.argv[1]                      # R or N
OUT = f"glm.{REG}.jsonl"
URL = os.environ["GLM_BASE_URL"].rstrip("/") + "/chat/completions"
KEY = open(os.path.expanduser("~/.config/ekbasis/cb_glm_key")).read().strip()
ST = [json.loads(l) for l in open(f"{SC}/corte_schema/data/st_new.{REG}.jsonl")]
done = {r["id"] for r in (json.loads(l) for l in open(OUT)) if "infra_error" not in r and not str(r.get("error","")).startswith("HTTPError")} if os.path.exists(OUT) else set()
SYS = ("You forecast what a database migration will do. Read the state and answer each question with a probability "
       "between 0 and 1. Reply with only a JSON object {\"lost\": <p>, \"fails\": <p>} and nothing else.")

def ask(s):
    qs = json.loads(s["questions"]) if isinstance(s["questions"], str) else s["questions"]
    user = (s["state"] + "\n\nQuestions:\n- lost: " + qs["lost"]["instructions"] + "\n- fails: " + qs["fails"]["instructions"]
            + "\n\nReply with only {\"lost\": p, \"fails\": p}.")
    body = {"model": "glm-5.3-flash", "temperature": 0, "max_tokens": 4000,
            "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": user}]}
    for attempt in range(2):
        t = time.time()
        b2 = dict(body, stream=True, stream_options={"include_usage": True})
        req = urllib.request.Request(URL, json.dumps(b2).encode(), {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
        txt, u = "", {}
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:     # streaming keeps the tunnel alive past 100 s
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:") or line == "data: [DONE]":
                        continue
                    ev = json.loads(line[5:])
                    if ev.get("usage"):
                        u = ev["usage"]
                    for ch in ev.get("choices") or []:
                        txt += (ch.get("delta") or {}).get("content") or ""
        except Exception as e:
            return {"id": s["id"], "infra_error": f"{type(e).__name__}: {str(e)[:120]}"}
        m = re.search(r"\{[^{}]*\"lost\"[^{}]*\}", txt)
        if m:
            try:
                j = json.loads(m.group(0))
                return {"id": s["id"], "p_lost": float(j["lost"]), "p_fails": float(j["fails"]), "secs": round(time.time()-t, 2),
                        "in": u.get("prompt_tokens"), "out": u.get("completion_tokens"), "attempt": attempt}
            except Exception:
                pass
        err = "unparsable: " + txt[-160:].replace("\n", " ")
    return {"id": s["id"], "error": err}

todo = [s for s in ST if s["id"] not in done and s.get("questions") and s["questions"] not in ("None", None, "{}")]
print(f"{REG}: {len(todo)} to ask, {len(done)} done", flush=True)
with cf.ThreadPoolExecutor(10) as ex, open(OUT, "a") as f:
    for i, fut in enumerate(cf.as_completed([ex.submit(ask, s) for s in todo])):
        r = fut.result()
        f.write(json.dumps(r) + "\n"); f.flush()
        if i % 10 == 0: print(i, r.get("id"), r.get("p_lost"), r.get("p_fails"), r.get("secs"), r.get("out"), r.get("error", ""), flush=True)
print("DONE", REG, flush=True)
