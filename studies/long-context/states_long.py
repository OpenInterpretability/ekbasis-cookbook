"""Long-context study (PREREG.md): the 184 v3 migrations (raw product inputs rebuilt in v4, regime R), with DISTRACTOR
tables from OTHER projects' real schemas inserted in the schema block of the product's state. No model calls.

    venv/bin/python states_long.py            -> data/req_<cond>.jsonl, data/items.json, data/cold_*.jsonl

The state is ekbasis.migrations.build_state (0.1.17, unchanged since 8071e38), reproduced here with two additions:
distractor DDL lines and their "Rows:" lines, at a depth (start/middle/end) relative to the relevant tables, and, in the
long conditions only, a header that says other tables of the database are shown. L0 must equal build_state byte for byte
(asserted for every item).
"""
import glob, hashlib, json, os, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "ekbasis"))
from ekbasis import migrations as M          # noqa: E402
from ekbasis import prompts as P             # noqa: E402
from tokenizers import Tokenizer             # noqa: E402

V4 = os.path.join(os.path.dirname(HERE), "v4", "data")
TOK = Tokenizer.from_file(os.path.join(HERE, "tok", "tokenizer.json"))
SEED = "ctxlong:20261011"
HEADER_L0 = "Schema (the tables the migration names, and the tables linked to them by foreign keys):"
HEADER_LONG = ("Schema (the tables the migration names, the tables linked to them by foreign keys, and other tables of "
               "the database):")
SLACK = 500                      # tokens left for the question and the chat template in each sequence
TARGETS = {"16k": 16000, "32k": 32000, "64k": 64000, "120k": 120000}
QS = {"lost": M.Q_LOST, "fails": M.Q_FAILS}
OUT = os.path.join(HERE, "data")


def ntok(s):
    return len(TOK.encode(s).ids)


def h(s):
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def load_raw():
    raw, best = {}, {}
    for d in ("items_v4", "items_d2"):
        for p in sorted(glob.glob(os.path.join(V4, d, "*.jsonl"))):
            for l in open(p):
                r = json.loads(l)
                if d == "items_v4":
                    raw[r["id"]] = r
                x = r.get("raw") or {}
                if x.get("catalog"):
                    n = len(x["catalog"].get("tables") or [])
                    if r["repo"] not in best or n > best[r["repo"]][0]:
                        best[r["repo"]] = (n, r["id"], x["catalog"], x["stats"])
    return raw, best


def refs(t):
    out = set()
    for k in t["cons"] or []:
        if k["type"] == "f":
            m = re.search(r"REFERENCES\s+((?:\"[^\"]+\"|[\w$]+)\.)?(\"[^\"]+\"|[\w$]+)", k["def"])
            if m:
                out.add(m.group(2).strip('"').lower())
    return out


def pool_tables(best):
    """Every table of every project's largest catalog: (repo, table, ddl, rows line, enums used {name: labels})."""
    pool = {}
    for repo, (_, src, cat, stats) in sorted(best.items()):
        en = cat.get("enums") or {}
        rows = []
        for t in cat.get("tables") or []:
            used = {c["typname"].lstrip("_") for c in t["cols"] or []}
            rows.append({"repo": repo, "name": t["name"], "disp": M.disp(t), "ddl": M.ddl(t),
                         "rows": M.table_facts(t, stats), "refs": refs(t),
                         "enums": {e: en[e] for e in sorted(used) if e in en}})
        pool[repo] = rows
    return pool


def distractors(item_id, repo, catalog, text, pool, rot_seed=None):
    """The item's eligible distractors, in order: projects in a seeded order, tables in catalog order within each one
    (a database that holds several applications' schemas). rot_seed (cold-latency requests): start each project at a
    seeded table, so the first table differs from any other request."""
    taken = {t["name"].lower() for t in catalog.get("tables") or []} | {e.lower() for e in (catalog.get("enums") or {})}
    repos = sorted(r for r in pool if r != repo)
    random.Random(f"{SEED}:{item_id}" + (f":{rot_seed}" if rot_seed else "")).shuffle(repos)
    out, names, enums = [], set(), {}
    for r in repos:
        rows = pool[r]
        if rot_seed:
            k = h(f"{rot_seed}:{r}") % len(rows)
            rows = rows[k:] + rows[:k]
        for d in rows:
            n = d["name"].lower()
            if n in taken or n in names or d["refs"] & taken:
                continue
            if re.search(r"(?<![\w$])[\"'`]?" + re.escape(d["name"]) + r"[\"'`]?(?![\w$])", text, re.I):
                continue
            if any(e.lower() in taken or (e in enums and enums[e] != r) for e in d["enums"]):
                continue
            out.append(d)
            names.add(n)
            for e in d["enums"]:
                enums.setdefault(e, r)
    return out


def build_long(catalog, stmts, stats, tool, transaction, facts, dis, depth, header):
    """build_state (0.1.17) with distractor tables placed at `depth` around the relevant ones (dis empty and header ==
    HEADER_L0 gives build_state exactly)."""
    tables = catalog.get("tables") or []
    byoid = {t["oid"]: t for t in tables}
    text = "\n".join(stmts)
    named = M.named_tables(text, tables)
    partners = []
    for t in tables:
        for k in t["cons"] or []:
            if k["type"] != "f" or k["ref"] not in byoid:
                continue
            if t in named and byoid[k["ref"]] not in named:
                partners.append(byoid[k["ref"]])
            if byoid[k["ref"]] in named and t not in named:
                partners.append(t)
    shown = []
    for t in named + partners:
        if t not in shown:
            shown.append(t)
    shown = shown[:M.MAX_TABLES]
    used = {c["typname"].lstrip("_") for t in shown for c in t["cols"] or []}
    enums = [f"{e}: " + ", ".join("'" + v + "'" for v in labels) for e, labels in (catalog.get("enums") or {}).items()
             if e in used or re.search(r"(?<![\w$])\"?" + re.escape(e) + r"\"?(?![\w$])", text)]
    seen = set()
    for d in dis:
        for e, labels in d["enums"].items():
            if e not in seen:
                seen.add(e)
                enums.append(f"{e}: " + ", ".join("'" + v + "'" for v in labels))
    rel_ddl = [M.ddl(t) for t in shown] or ["(none of the tables it names exists yet)"]
    rel_rows = [M.table_facts(t, stats) for t in shown]
    if depth == "start":
        cut = 0
    elif depth == "end":
        cut = len(dis)
    else:                                   # middle: half of the distractors' characters before the relevant tables
        tot, acc, cut = sum(len(d["ddl"]) + len(d["rows"]) for d in dis), 0, 0
        while cut < len(dis) and acc + len(dis[cut]["ddl"]) + len(dis[cut]["rows"]) <= tot / 2:
            acc += len(dis[cut]["ddl"]) + len(dis[cut]["rows"])
            cut += 1
    before, after = dis[:cut], dis[cut:]
    parts = [header]
    parts += [d["ddl"] for d in before] + rel_ddl + [d["ddl"] for d in after]
    if enums:
        parts.append("Enum types: " + "; ".join(enums))
    parts += ["", "Rows:"] + [d["rows"] for d in before] + rel_rows + [d["rows"] for d in after]
    others = [M.disp(t) for t in tables if t not in shown]
    if others:
        parts.append("Other tables: " + ", ".join(others[:40]) + (", ..." if len(others) > 40 else ""))
    if facts:
        parts += ["", "Facts: " + " ".join(facts)]
    rules = M.RULES_TX.format(tool=M.TOOL_NAMES.get(tool, M.TOOL_NAMES["generic"])) if transaction else M.RULES_AUTO
    return P.world_state(rules, "\n".join(parts), stmts), [M.disp(t) for t in shown], cut


def state_for(x, item_id, repo, pool, target, depth, rot_seed=None):
    """The longest state whose token count is <= target - SLACK (greedy over the ordered distractors)."""
    facts = [f"Run on this schema with no rows, the migration fails: {x['schema_error']}."] if x["schema_error"] else []
    args = (x["catalog"], x["statements"], x["stats"], x["tool"], x["transaction"], facts)
    dis = distractors(item_id, repo, x["catalog"], "\n".join(x["statements"]), pool, rot_seed)
    goal = target - SLACK
    # token estimate per distractor (ddl + rows + 2 newlines), then exact correction
    est = [ntok(d["ddl"]) + ntok(d["rows"]) + 2 for d in dis]
    base = ntok(build_long(*args, [], depth, HEADER_LONG)[0])
    n, acc = 0, base
    while n < len(dis) and acc + est[n] <= goal:
        acc += est[n]
        n += 1
    while True:
        st, shown, cut = build_long(*args, dis[:n], depth, HEADER_LONG)
        t = ntok(st)
        if t <= goal or n == 0:
            break
        n -= 1
    if n == len(dis):
        raise RuntimeError(f"{item_id}: distractor pool exhausted at {t} tokens for target {target}")
    return st, t, n, cut, len(dis)


def main():
    os.makedirs(OUT, exist_ok=True)
    raw, best = load_raw()
    pool = pool_tables(best)
    labels = [json.loads(l) for l in open(os.path.join(V4, "labels_v3.jsonl"))]
    old = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(os.path.dirname(V4), "st", "req_t2_old.R.jsonl"))}
    ids = [l["id"] for l in labels]
    lab = {l["id"]: l for l in labels}
    # depth for 64k and 120k: balanced within risky and within benign, in sha256 order
    depth = {}
    for risky in (True, False):
        grp = sorted((i for i in ids if bool(lab[i]["label_product"]["lost"] or lab[i]["label_product"]["fails"]) == risky),
                     key=lambda i: h(f"{SEED}:depth:{i}"))
        for k, i in enumerate(grp):
            depth[i] = ("start", "middle", "end")[k % 3]
    items = []
    reqs = {c: [] for c in ["L0", "L0h"] + list(TARGETS)}
    if sys.argv[1:] == ["cold"]:            # rebuild only the cold-latency requests (the others are deterministic)
        reqs["L0"] = [json.loads(l) for l in open(os.path.join(OUT, "req_L0.jsonl"))]
        ids_build = []
    else:
        ids_build = ids
    for i in ids_build:
        x = raw[i]["raw"]
        assert x["decided"] is None, i
        facts = [f"Run on this schema with no rows, the migration fails: {x['schema_error']}."] if x["schema_error"] else []
        args = (x["catalog"], x["statements"], x["stats"], x["tool"], x["transaction"], facts)
        s0, shown0 = M.build_state(*args)
        s0b, shown0b, _ = build_long(*args, [], "middle", HEADER_L0)
        assert s0 == s0b and s0 == old[i]["state"], f"L0 mismatch {i}"
        rec = {"id": i, "repo": lab[i]["repo"], "depth_long": depth[i], "transaction": x["transaction"],
               "schema_error_autocommit": bool(x["schema_error"]), "shown": shown0, "tokens": {}}
        reqs["L0"].append({"id": i, "cond": "L0", "state": s0, "questions": QS})
        rec["tokens"]["L0"] = ntok(s0)
        sh, _, _ = build_long(*args, [], "middle", HEADER_LONG)
        reqs["L0h"].append({"id": i, "cond": "L0h", "state": sh, "questions": QS})
        rec["tokens"]["L0h"] = ntok(sh)
        for c, T in TARGETS.items():
            d = depth[i] if c in ("64k", "120k") else "middle"
            st, t, n, cut, avail = state_for(x, i, lab[i]["repo"], pool, T, d)
            reqs[c].append({"id": i, "cond": c, "depth": d, "state": st, "questions": QS})
            rec["tokens"][c] = t
            rec.setdefault("n_distractors", {})[c] = n
            rec.setdefault("before", {})[c] = cut
            rec["pool"] = avail
        items.append(rec)
        print(i, rec["tokens"], flush=True)
    for c, rs in reqs.items():
        if not ids_build:
            break
        with open(os.path.join(OUT, f"req_{c}.jsonl"), "w") as f:
            for r in rs:
                f.write(json.dumps(r) + "\n")
    # cold latency: 5 items, unique distractor rotation, depth end, one request per length (+ L0 as built)
    cold_ids = sorted(ids, key=lambda i: h(f"{SEED}:cold:{i}"))[:5]
    with open(os.path.join(OUT, "req_cold.jsonl"), "w") as f:
        firsts = set()
        for c in ["L0"] + list(TARGETS):
            for i in cold_ids:
                x = raw[i]["raw"]
                if c == "L0":
                    st = next(r["state"] for r in reqs["L0"] if r["id"] == i)
                else:
                    for k in range(50):     # the first distractor table differs from every other cold request's
                        st, *_ = state_for(x, i, lab[i]["repo"], pool, TARGETS[c], "end", rot_seed=f"cold:{c}:{i}:{k}")
                        first = st.split(HEADER_LONG + "\n", 1)[1].split(");", 1)[0]
                        if first not in firsts:
                            break
                    firsts.add(first)
                f.write(json.dumps({"id": f"cold:{c}:{i}", "item": i, "cond": c, "state": st, "questions": QS,
                                    "tokens": ntok(st)}) + "\n")
    if not ids_build:
        return
    json.dump({"items": items, "cold_ids": cold_ids, "pool_sources": {r: best[r][1] for r in best}},
              open(os.path.join(OUT, "items.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
