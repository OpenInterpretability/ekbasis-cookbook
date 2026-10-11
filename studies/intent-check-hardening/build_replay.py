"""Rebuilds the 13 recorded non-serves_user decisions of the official AgentDojo run (6 blocks, 7 unsure) from its traces:
events = every tool call and result before the judged call, exactly as intent_defense._events built them."""
import json, sys
OFF = sys.argv[1]; out = open(sys.argv[2], "w")
dec = [json.loads(l) for l in open(f"{OFF}/full/intent_decisions.jsonl")]
n = 0
for d in dec:
    if d["verdict"] == "serves_user":
        continue
    it = d["it"] or "none"
    log = json.load(open(f"{OFF}/full/logs/local-glm-5.3-flash-low-intent_check/{d['suite']}/{d['ut']}/"
                        f"{'none' if d['it'] is None else 'important_instructions'}/{it}.json"))
    events = []
    for m in log["messages"]:
        if m["role"] == "assistant" and m.get("tool_calls"):
            hit = [c for c in m["tool_calls"] if c["function"] == d["call"] and json.dumps(c["args"])[:500] == d["args"]]
            if hit and len(events) == d["n_prior_tool_events"]:
                args = hit[0]["args"]
                break
        if m["role"] == "tool" and m.get("tool_call"):
            res = m["error"] or "".join(b["content"] for b in m["content"] or [] if b.get("type") == "text")
            events.append({"kind": "tool", "name": m["tool_call"]["function"], "input": m["tool_call"]["args"], "result": res})
    else:
        raise SystemExit(f"not found: {d}")
    req = next(m for m in log["messages"] if m["role"] == "user")["content"][0]["content"]
    out.write(json.dumps({"id": f"r{n}", "suite": d["suite"], "ut": d["ut"], "it": d["it"], "kind": "recorded",
                          "orig_verdict": d["verdict"], "orig_p": d["p"], "request": req, "events": events,
                          "action": {"name": d["call"], "input": args}}) + "\n")
    n += 1
print(n, "recorded decisions rebuilt")
