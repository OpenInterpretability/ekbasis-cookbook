"""Dev/test split, stratified by design category (seed 20261011): about a third of each category goes to dev."""
import json
import random

from scenarios import SCENARIOS

rng = random.Random(20261011)
dev, test = [], []
for d in sorted({s["design"] for s in SCENARIOS}):
    ids = [s["id"] for s in SCENARIOS if s["design"] == d]
    rng.shuffle(ids)
    k = round(len(ids) / 3)
    dev += sorted(ids[:k])
    test += sorted(ids[k:])
json.dump({"dev": sorted(dev), "test": sorted(test)}, open("split.json", "w"), indent=1)
print(len(dev), len(test))
