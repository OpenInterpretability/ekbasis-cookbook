"""Gateway queue vs model time, from the Server-Timing header of each Ekbasis answer."""
import json, re, statistics as st
P = [json.loads(l) for l in open("preds/ekbasis.jsonl")]
ok = [p for p in P if "error" not in p]
def t(p, k):
    m = re.search(k + r';(?:desc="[^"]*";)?dur=([\d.]+)', p.get("server_timing") or "")
    return float(m.group(1)) if m else None
q = [t(p, "queue") for p in ok if t(p, "queue") is not None]
m = [t(p, "model") for p in ok if t(p, "model") is not None]
w = [p["secs"] for p in ok]
tok = [p["usage"]["input_tokens"] for p in ok if p.get("usage")]
pct = lambda xs, f: sorted(xs)[min(len(xs) - 1, int(f * len(xs)))]
print(f"answers {len(ok)}, errors {len(P) - len(ok)}")
for nm, xs, u in (("queue", q, "ms"), ("model", m, "ms"), ("wall", w, "s")):
    print(f"{nm}: median {st.median(xs):.0f}{u} p90 {pct(xs, .9):.0f}{u} max {max(xs):.0f}{u} total {sum(xs) / (1000 if u == 'ms' else 1) / 60:.1f} min")
print(f"input tokens (billed, as reported): total {sum(tok):,}, median {st.median(tok):.0f}, max {max(tok)}")
