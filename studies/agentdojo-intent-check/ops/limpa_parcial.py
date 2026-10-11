"""Drops intent_check decisions of runs that never finished (no line in results.jsonl), e.g. killed for the pause."""
import json, sys
out = sys.argv[1]
done = {(r["cond"], r["suite"], r["ut"], r["it"]) for r in map(json.loads, open(f"{out}/results.jsonl"))}
try:
    dec = [json.loads(l) for l in open(f"{out}/intent_decisions.jsonl")]
except FileNotFoundError:
    sys.exit()
keep = [d for d in dec if (d["cond"], d["suite"], d["ut"], d["it"]) in done]
with open(f"{out}/intent_decisions.jsonl", "w") as f:
    f.writelines(json.dumps(d) + "\n" for d in keep)
print(f"decisões removidas (execução incompleta): {len(dec) - len(keep)}")
