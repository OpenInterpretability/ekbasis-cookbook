"""The fixed order of the 120k run (PREREG section 5, step 7): risky and benign each in sha256 order, interleaved
56:128 so that every prefix is stratified."""
import hashlib, json, os
HERE = os.path.dirname(os.path.abspath(__file__))
L = [json.loads(l) for l in open(os.path.join(os.path.dirname(HERE), "v4", "data", "labels_v3.jsonl"))]
h = lambda s: hashlib.sha256(s.encode()).hexdigest()
rk = sorted((x["id"] for x in L if x["label_product"]["lost"] or x["label_product"]["fails"]), key=lambda i: h("ctxlong:20261011:order:" + i))
bn = sorted((x["id"] for x in L if not (x["label_product"]["lost"] or x["label_product"]["fails"])), key=lambda i: h("ctxlong:20261011:order:" + i))
out, a, b = [], 0, 0
while a < len(rk) or b < len(bn):
    if b >= len(bn) or (a < len(rk) and (a + 1) / len(rk) <= (b + 1) / len(bn)):
        out.append(rk[a]); a += 1
    else:
        out.append(bn[b]); b += 1
open(os.path.join(HERE, "data", "order_120k.txt"), "w").write("\n".join(out) + "\n")
print(len(out), out[:5])
