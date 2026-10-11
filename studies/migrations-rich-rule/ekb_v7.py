"""EKB 0.1.21 verdicts, in their own process (the v7 product package), with the frozen analysis code:
Rails v7 -> fw_eval_rails7/eval/analysis_v7.product; P5 -> the NEW verdict of p5/analysis_p5.py (probe_fails -> fails;
analysis_v3.product_verdict; schema_only_plan sets p_fail = 0). Reads no label of v7 (P5's labels file carries the
product fields; P5 is dev).  python3 ekb_v7.py OUT.json"""
import json, os, sys, glob
HERE = os.path.dirname(os.path.abspath(__file__)); SP = os.path.dirname(HERE)
R7 = os.path.join(SP, "fw_eval_rails7")
sys.path.insert(0, os.path.join(R7, "eval"))
import analysis_v7 as A7                     # noqa: E402  (swaps in the v7 ekbasis)
M = A7.M
out = {"v7": {}, "p5": {}}
A7.V4.HERE = os.path.join(R7, "eval")
rows, _ = A7.V4.load()
preds = {p["id"]: p for p in map(json.loads, open(os.path.join(R7, "eval", "preds", "v7.jsonl"))) if "error" not in p}
for r in rows:
    out["v7"][r["id"]] = A7.product(r, preds.get(r["id"]))
sys.path.insert(0, os.path.join(SP, "pr_eval3"))
import analysis_v3 as V3                     # noqa: E402
V3.M = M
labs = {r["id"]: r for r in map(json.loads, open(os.path.join(R7, "p5", "data", "labels_v3.jsonl")))}
pp = {p["id"]: p for p in map(json.loads, open(os.path.join(R7, "p5", "preds", "p5.jsonl"))) if "error" not in p}
stm = {}
for p in glob.glob(os.path.join(SP, "p2", "data", "items_p2", "*.jsonl")):
    for l in open(p):
        x = json.loads(l); stm[x["id"]] = x["raw"]["statements"]
for k, l in labs.items():
    if l["decided"] == "probe_fails":
        out["p5"][k] = (True, "fails"); continue
    v = V3.product_verdict(l, pp[k]) if (l["decided"] or k in pp) else (True, "cannot_foresee")
    if not l["decided"] and not l["schema_error"] and k in pp and M.schema_only_plan(stm[k]):
        fv = M.FileVerdict(l["path"], l["tool"], l["transaction"], p_lost=pp[k]["p_lost"], p_fail=0.0)
        v = (fv.p_lost >= 0.5, fv.kind)
    out["p5"][k] = v
json.dump(out, open(sys.argv[1], "w"))
print({k: len(v) for k, v in out.items()}, M.__file__)
