"""Execution side of the study: a throwaway PostgreSQL 16, a generic seeder, snapshots and the loss/failure labels.

Labels come only from running the migration (never from its text):
- lost: some non-NULL value stored before the migration is afterwards in no table at all (row deleted, table or column
  dropped without the values being copied, value overwritten or changed by a cast).
- fails: some statement ends with an error on the seeded database (items whose statements already fail on the same
  schema with no rows are excluded upstream: those are environment failures, not consequences of the data).
- half_applied: fails, and the database (schema or data) still changed.
Runner semantics for the primary labels: statements one by one in autocommit, continuing after an error (psql -f).
"""
from __future__ import annotations

import hashlib
import random
import re
import uuid
from collections import defaultdict

import psycopg
from psycopg import sql as S

DSN = "host=127.0.0.1 port=55491 user=postgres"
N_ROWS = 20
P_NULL = 0.25
STMT_TIMEOUT_MS = 20000
SYS_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")


def connect(db: str, autocommit: bool = True) -> psycopg.Connection:
    return psycopg.connect(f"{DSN} dbname={db}", autocommit=autocommit)


def admin():
    return connect("postgres")


def drop_db(name: str):
    with admin() as a:
        a.execute(S.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(S.Identifier(name)))


def clone_db(src: str, dst: str):
    with admin() as a:
        a.execute(S.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(S.Identifier(dst)))
        a.execute(S.SQL("CREATE DATABASE {} TEMPLATE {}").format(S.Identifier(dst), S.Identifier(src)))


def create_db(name: str):
    with admin() as a:
        a.execute(S.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(S.Identifier(name)))
        a.execute(S.SQL("CREATE DATABASE {}").format(S.Identifier(name)))


# ---------------------------------------------------------------- running statements

def run_statements(db: str, stmts: list[str], transaction: bool = False) -> list[dict]:
    """Each statement's outcome: {"ok": bool, "error": str|None}. transaction=False: autocommit, continue after errors.
    transaction=True: one transaction, stop at the first error and roll back (later statements: ok=None)."""
    res = []
    with connect(db, autocommit=not transaction) as c:
        c.execute(f"SET statement_timeout = {STMT_TIMEOUT_MS}")
        c.execute("SET client_min_messages = warning")
        failed = False
        for s in stmts:
            if failed:
                res.append({"ok": None, "error": None})
                continue
            try:
                c.execute(s, prepare=False)
                res.append({"ok": True, "error": None})
            except psycopg.Error as e:
                msg = (e.diag.message_primary or str(e)).strip()
                res.append({"ok": False, "error": f"{e.sqlstate}: {msg}"[:300]})
                if transaction:
                    failed = True
                    c.rollback()
        if transaction and not failed:
            c.commit()
    return res


def apply_progression(db: str, stmts: list[str]) -> str:
    """Advance the schema-only database by one migration the way a migration tool would: whole file in one transaction;
    if that fails (or the file cannot run in a transaction), statement by statement. Returns 'tx', 'auto' or 'auto-err'."""
    r = run_statements(db, stmts, transaction=True)
    if all(x["ok"] for x in r):
        return "tx"
    r = run_statements(db, stmts, transaction=False)
    return "auto" if all(x["ok"] for x in r) else "auto-err"


# ---------------------------------------------------------------- catalog

CAT_TABLES = """
SELECT c.oid, n.nspname, c.relname, c.relkind, c.relispartition
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r','p') AND n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
  AND n.nspname NOT LIKE 'pg_temp%' AND n.nspname NOT LIKE 'pg_toast%'
ORDER BY n.nspname, c.relname"""

CAT_COLS = """
SELECT a.attrelid, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, a.atthasdef, a.attidentity,
       a.attgenerated, a.attnum, t.typtype, t.typcategory, t.typname,
       COALESCE(bt.typname, et.typname, t.typname) AS basename, a.atttypmod, a.atttypid, t.typelem,
       pg_get_expr(d.adbin, d.adrelid)
FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid
LEFT JOIN pg_type bt ON bt.oid = t.typbasetype AND t.typtype = 'd'
LEFT JOIN pg_type et ON et.oid = t.typelem AND t.typcategory = 'A'
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE a.attnum > 0 AND NOT a.attisdropped AND a.attrelid = ANY(%s)
ORDER BY a.attrelid, a.attnum"""

CAT_CONS = """
SELECT conrelid, conname, contype, conkey, confrelid, confkey, pg_get_constraintdef(oid), confdeltype
FROM pg_constraint WHERE conrelid = ANY(%s) ORDER BY conrelid, conname"""

CAT_IDX = """
SELECT i.indrelid, pg_get_indexdef(i.indexrelid), i.indisunique, i.indisprimary
FROM pg_index i WHERE i.indrelid = ANY(%s) ORDER BY 1, 2"""


def catalog(con) -> dict:
    tabs = con.execute(CAT_TABLES).fetchall()
    oids = [t[0] for t in tabs]
    T = {}
    for oid, ns, rel, kind, ispart in tabs:
        T[oid] = {"oid": oid, "schema": ns, "name": rel, "kind": kind, "ispart": ispart, "cols": [], "cons": [], "idx": []}
    for r in con.execute(CAT_COLS, (oids,)).fetchall():
        (rid, name, ftype, notnull, hasdef, ident, gen, num, typtype, typcat, typname, basename, typmod, typid, typelem,
         defexpr) = r
        T[rid]["cols"].append({"name": name, "type": ftype, "notnull": notnull, "hasdef": hasdef, "identity": ident,
                               "generated": gen, "num": num, "typtype": typtype, "typcat": typcat, "typname": typname,
                               "base": basename, "typmod": typmod, "typid": typid, "default": defexpr})
    for r in con.execute(CAT_CONS, (oids,)).fetchall():
        rid, cname, ctype, conkey, confrel, confkey, cdef, deltype = r
        T[rid]["cons"].append({"name": cname, "type": ctype, "key": list(conkey or []), "ref": confrel,
                               "refkey": list(confkey or []), "def": cdef, "ondelete": deltype})
    for r in con.execute(CAT_IDX, (oids,)).fetchall():
        T[r[0]]["idx"].append({"def": r[1], "unique": r[2], "primary": r[3]})
    enums = defaultdict(list)
    for tname, label in con.execute("SELECT t.typname, e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                                    "ORDER BY t.typname, e.enumsortorder"):
        enums[tname].append(label)
    for t in T.values():
        t["colnum"] = {c["num"]: c["name"] for c in t["cols"]}
    return {"tables": T, "enums": dict(enums)}


def qname(t: dict) -> S.Composed:
    return S.SQL("{}.{}").format(S.Identifier(t["schema"]), S.Identifier(t["name"]))


def disp(t: dict) -> str:
    return t["name"] if t["schema"] == "public" else f"{t['schema']}.{t['name']}"


# ---------------------------------------------------------------- seeding

TEXT = {"text", "varchar", "bpchar", "citext", "name"}
INT = {"int2": (1, 32000), "int4": (100000, 2_000_000_000), "int8": (10_000_000_000, 900_000_000_000_000)}


def _tok(rng):
    return "zq" + "".join(rng.choice("0123456789abcdef") for _ in range(10))


def gen_value(col: dict, enums: dict, rng: random.Random):
    """(text literal or None, kind) with kind 'dist' (distinctive: findable anywhere later) or 'low'."""
    base, typmod, cat = col["base"], col["typmod"], col["typcat"]
    is_array = cat == "A"
    if col["typtype"] == "e" or (is_array and base in enums):
        labels = enums.get(col["typname"].lstrip("_") if is_array else col["typname"]) or enums.get(base) or []
        if not labels:
            return None, "low"
        v = rng.choice(labels)
        return ("{" + '"' + v + '"' + "}" if is_array else v), "low"
    v, kind = None, "low"
    if base in TEXT:
        lim = typmod - 4 if typmod and typmod > 4 and not is_array else None
        if lim is None or lim >= 12:
            v, kind = _tok(rng), "dist"
        else:
            v = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(lim if base == "bpchar" else min(lim, 6)))
    elif base in INT:
        lo, hi = INT[base]
        v, kind = str(rng.randint(lo, hi)), ("dist" if base != "int2" else "low")
    elif base == "numeric":
        p = ((typmod - 4) >> 16) & 0xFFFF if typmod and typmod > 4 else 0
        s = (typmod - 4) & 0xFFFF if typmod and typmod > 4 else 2
        intdig = (p - s) if p else 9
        if intdig >= 6:
            v = str(rng.randint(100000, 10 ** min(intdig, 9) - 1)) + (".25" if s >= 2 else "")
            kind = "dist"
        else:
            v = str(rng.randint(1, max(1, 10 ** max(intdig, 1) - 1)))
    elif base in ("float4", "float8"):
        v, kind = f"{rng.randint(100000, 999999)}.5", "dist"
    elif base == "bool":
        v = rng.choice(["true", "false"])
    elif base == "uuid":
        v, kind = str(uuid.UUID(int=rng.getrandbits(128), version=4)), "dist"
    elif base == "date":
        v = f"{rng.randint(2001, 2024)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    elif base in ("timestamp", "timestamptz"):
        v = (f"{rng.randint(2001, 2024)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d} "
             f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}")
    elif base in ("time", "timetz"):
        v = f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00"
    elif base == "interval":
        v = f"{rng.randint(1, 90)} days"
    elif base in ("json", "jsonb"):
        v, kind = '{"zk": "' + _tok(rng) + '"}', "dist"
    elif base == "bytea":
        v = "\\x" + rng.randbytes(6).hex()
    elif base in ("inet", "cidr"):
        v = f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.0" + ("/24" if base == "cidr" else "")
    elif base == "citext":
        v, kind = _tok(rng), "dist"
    elif base == "tsvector":                        # normally kept by a trigger, which seeding bypasses
        v = _tok(rng)
    elif base == "xml":
        v = "<v>" + _tok(rng) + "</v>"
    else:
        return None, "low"
    if is_array and v is not None:
        v = "{" + '"' + v.replace('"', '\\"') + '"' + "}"
    return v, kind


def _topo(tables: dict) -> list:
    deps = {oid: {c["ref"] for c in t["cons"] if c["type"] == "f" and c["ref"] != oid and c["ref"] in tables}
            for oid, t in tables.items()}
    order, seen, temp = [], set(), set()

    def visit(o):
        if o in seen or o in temp:
            return
        temp.add(o)
        for d in deps[o]:
            visit(d)
        temp.discard(o)
        seen.add(o)
        order.append(o)

    for o in tables:
        visit(o)
    return order


def seed(db: str, rng: random.Random, n_rows: int = N_ROWS) -> dict:
    """Insert n_rows synthetic rows into every table (FKs pointed at seeded parents; checks, uniques and NOT NULL
    enforced; FK triggers bypassed while seeding, dangling references fixed afterwards). Returns {table: rows seeded}."""
    con = connect(db, autocommit=False)
    con.execute("SET session_replication_role = replica")
    con.execute(f"SET statement_timeout = {STMT_TIMEOUT_MS}")
    cat = catalog(con)
    T, enums = cat["tables"], cat["enums"]
    seedable = {o: t for o, t in T.items() if not t["ispart"]}
    inserted = defaultdict(list)          # oid -> list of {col: text value}
    counts = {}
    for oid in _topo(seedable):
        t = seedable[oid]
        cols = [c for c in t["cols"] if not c["generated"]]
        fks = [c for c in t["cons"] if c["type"] == "f"]
        fkcols = {t["colnum"][k] for f in fks for k in f["key"]}
        pkcols = {t["colnum"][k] for c in t["cons"] if c["type"] in ("p", "u") for k in c["key"]}
        ok = 0
        for i in range(n_rows):
            for attempt in range(6):
                row = {}
                for c in cols:
                    if c["name"] in fkcols:
                        continue
                    nullable = not c["notnull"] and c["name"] not in pkcols
                    if nullable and rng.random() < P_NULL:
                        row[c["name"]] = None
                        continue
                    v, _ = gen_value(c, enums, rng)
                    if v is None and c["notnull"] and c["hasdef"]:
                        continue                    # leave it to the default
                    row[c["name"]] = v
                for f in fks:
                    names = [t["colnum"][k] for k in f["key"]]
                    parent = T.get(f["ref"])
                    prow = inserted.get(f["ref"])
                    nullable = all(not next(c for c in t["cols"] if c["name"] == nm)["notnull"] for nm in names)
                    if nullable and (rng.random() < P_NULL or not prow):
                        for nm in names:
                            row[nm] = None
                        continue
                    if prow:
                        pr = rng.choice(prow)
                        pnames = [parent["colnum"][k] for k in f["refkey"]]
                        for nm, pn in zip(names, pnames):
                            row[nm] = pr.get(pn)
                    else:                           # cycle: fixed after all tables are seeded
                        for nm in names:
                            c = next(c for c in t["cols"] if c["name"] == nm)
                            row[nm] = gen_value(c, enums, rng)[0]
                ret = S.SQL(", ").join(S.SQL("{}::text").format(S.Identifier(c["name"])) for c in t["cols"])
                if not row:
                    q = S.SQL("INSERT INTO {} DEFAULT VALUES RETURNING {}").format(qname(t), ret)
                    params = []
                else:
                    names = list(row)
                    typ = {c["name"]: c["type"] for c in cols}
                    q = S.SQL("INSERT INTO {} ({}) OVERRIDING SYSTEM VALUE VALUES ({}) RETURNING {}").format(
                        qname(t), S.SQL(", ").join(S.Identifier(n) for n in names),
                        S.SQL(", ").join(S.SQL("%s::" + typ[n]) for n in names), ret)
                    params = [row[n] for n in names]
                try:
                    con.execute("SAVEPOINT r")
                    cur = con.execute(q, params, prepare=False)
                    vals = cur.fetchone()
                    con.execute("RELEASE SAVEPOINT r")
                    inserted[oid].append({c["name"]: v for c, v in zip(t["cols"], vals)})
                    ok += 1
                    break
                except psycopg.Error:
                    con.execute("ROLLBACK TO SAVEPOINT r")
        counts[disp(t)] = ok
    con.commit()
    _fix_dangling(con, T)
    con.commit()
    con.close()
    return counts


def _txt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _fix_dangling(con, T):
    """Point every dangling FK at an existing parent row (or NULL it, or delete the row): seeding went around FK checks."""
    for _ in range(4):
        changed = False
        for oid, t in T.items():
            if t["ispart"]:
                continue
            for f in [c for c in t["cons"] if c["type"] == "f"]:
                p = T.get(f["ref"])
                if p is None:
                    continue
                ch = [t["colnum"][k] for k in f["key"]]
                pa = [p["colnum"][k] for k in f["refkey"]]
                cond = S.SQL(" AND ").join(S.SQL("p.{} = c.{}").format(S.Identifier(a), S.Identifier(b)) for a, b in zip(pa, ch))
                notnull = S.SQL(" AND ").join(S.SQL("c.{} IS NOT NULL").format(S.Identifier(b)) for b in ch)
                dangling = S.SQL("{} AND NOT EXISTS (SELECT 1 FROM {} p WHERE {})").format(notnull, qname(p), cond)
                n = con.execute(S.SQL("SELECT count(*) FROM {} c WHERE {}").format(qname(t), dangling)).fetchone()[0]
                if not n:
                    continue
                changed = True
                prow = con.execute(S.SQL("SELECT {} FROM {} ORDER BY random() LIMIT 1").format(
                    S.SQL(", ").join(S.Identifier(a) for a in pa), qname(p))).fetchone()
                try:
                    con.execute("SAVEPOINT f")
                    if prow is not None:
                        con.execute(S.SQL("UPDATE {} c SET {} WHERE {}").format(
                            qname(t), S.SQL(", ").join(S.SQL("{} = %s").format(S.Identifier(b)) for b in ch), dangling),
                            list(prow))
                    else:
                        raise psycopg.errors.Error("no parent")
                    con.execute("RELEASE SAVEPOINT f")
                except psycopg.Error:
                    con.execute("ROLLBACK TO SAVEPOINT f")
                    try:
                        con.execute("SAVEPOINT g")
                        con.execute(S.SQL("UPDATE {} c SET {} WHERE {}").format(
                            qname(t), S.SQL(", ").join(S.SQL("{} = NULL").format(S.Identifier(b)) for b in ch), dangling))
                        con.execute("RELEASE SAVEPOINT g")
                    except psycopg.Error:
                        con.execute("ROLLBACK TO SAVEPOINT g")
                        con.execute(S.SQL("DELETE FROM {} c WHERE {}").format(qname(t), dangling))
        con.commit()
        if not changed:
            return


# ---------------------------------------------------------------- snapshots

def snapshot(db: str) -> dict:
    """Every row of every regular table (partitions included, partitioned parents skipped), as text."""
    with connect(db) as con:
        cat = catalog(con)
        out = {}
        for t in cat["tables"].values():
            if t["kind"] != "r":
                continue
            cols = [c["name"] for c in t["cols"]]
            if not cols:
                out[disp(t)] = {"cols": [], "rows": []}
                continue
            q = S.SQL("SELECT {} FROM ONLY {}").format(
                S.SQL(", ").join(S.SQL("{}::text").format(S.Identifier(c)) for c in cols), qname(t))
            rows = con.execute(q).fetchall()
            out[disp(t)] = {"cols": cols, "rows": [list(r) for r in rows]}
        fp = schema_fingerprint(con)
    return {"tables": out, "schema": fp, "catalog": cat}


def schema_fingerprint(con) -> str:
    q = """SELECT string_agg(x, E'\\n' ORDER BY x) FROM (
      SELECT n.nspname||'.'||c.relname||'.'||a.attname||':'||format_type(a.atttypid,a.atttypmod)||':'||a.attnotnull||':'||
             COALESCE(pg_get_expr(d.adbin,d.adrelid),'') AS x
      FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
      LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
      WHERE a.attnum>0 AND NOT a.attisdropped AND n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
        AND c.relkind IN ('r','p','v','m','i')
      UNION ALL SELECT conrelid::regclass::text||':'||conname||':'||pg_get_constraintdef(oid) FROM pg_constraint
        WHERE connamespace NOT IN (SELECT oid FROM pg_namespace WHERE nspname IN ('pg_catalog','information_schema'))
      UNION ALL SELECT 'type:'||typname||':'||COALESCE((SELECT string_agg(enumlabel,',' ORDER BY enumsortorder)
             FROM pg_enum WHERE enumtypid=t.oid),'') FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
        WHERE n.nspname NOT IN ('pg_catalog','information_schema','pg_toast') AND t.typtype IN ('e','d','c')
      UNION ALL SELECT 'fn:'||p.oid::regprocedure::text||':'||md5(p.prosrc) FROM pg_proc p JOIN pg_namespace n ON
        n.oid=p.pronamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema')
      UNION ALL SELECT 'trg:'||tgrelid::regclass::text||':'||tgname FROM pg_trigger WHERE NOT tgisinternal
    ) s"""
    r = con.execute(q).fetchone()[0] or ""
    return hashlib.sha256(r.encode()).hexdigest()


def data_fingerprint(snap: dict) -> str:
    h = hashlib.sha256()
    for name in sorted(snap["tables"]):
        t = snap["tables"][name]
        h.update(name.encode())
        h.update(repr(t["cols"]).encode())
        for r in sorted(map(repr, t["rows"])):
            h.update(r.encode())
    return h.hexdigest()


# ---------------------------------------------------------------- the loss label

TOKEN_RE = re.compile(r"zq[0-9a-f]{10}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d{6,}(?:\.\d+)?")
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ t](\d{2}:\d{2}:\d{2})")


def norm(v: str) -> str:
    s = v.strip().lower()
    if s in ("t", "true"):
        return "true"
    if s in ("f", "false"):
        return "false"
    m = TS_RE.match(s)
    if m:
        return m.group(1) + " " + m.group(2)
    if re.fullmatch(r"-?\d+\.\d+", s):
        s = s.rstrip("0").rstrip(".")
    return s


def norm_tok(tok: str) -> str:
    return tok.rstrip("0").rstrip(".") if "." in tok and not tok.startswith("zq") and "-" not in tok else tok


def kinds_for(cat: dict) -> dict:
    """{table: {col: 'dist'|'low'|'fk'}} for the pre-migration catalog (mirrors gen_value's distinctiveness)."""
    rng = random.Random(0)
    out = {}
    for t in cat["tables"].values():
        if t["kind"] != "r":
            continue
        fkcols = {t["colnum"][k] for f in t["cons"] if f["type"] == "f" for k in f["key"]}
        d = {}
        for c in t["cols"]:
            if c["name"] in fkcols:
                d[c["name"]] = "fk"
            else:
                d[c["name"]] = gen_value(c, cat["enums"], rng)[1]
        out[disp(t)] = d
    # partitions inherit the parent's FKs
    return out


def loss_label(pre: dict, post: dict) -> dict:
    kinds = kinds_for(pre["catalog"])
    # post index: token -> set of (table, row index); and per post row its normalized cells
    tok_rows = defaultdict(set)          # token -> post rows holding it anywhere
    tok_home = defaultdict(set)          # token -> post rows holding it outside an FK column (the row's own value),
                                         # or in a column that did not exist before (data moved by the migration)
    pre_cols = {(tn, c) for tn, t in pre["tables"].items() for c in t["cols"]}
    post_cells = {}
    cell_rows = defaultdict(set)         # normalized whole cell -> post rows (rows inserted by migrations carry no tokens)
    post_fk = {disp(t): {t["colnum"][k] for f in t["cons"] if f["type"] == "f" for k in f["key"]}
               for t in post["catalog"]["tables"].values()}
    for pt, t in post["tables"].items():
        fkc = post_fk.get(pt, set())
        for i, r in enumerate(t["rows"]):
            post_cells[(pt, i)] = [None if v is None else norm(v) for v in r]
            for nv in post_cells[(pt, i)]:
                if nv is not None and len(nv) >= 6:
                    cell_rows[nv].add((pt, i))
            for c, v in zip(t["cols"], r):
                if v is None:
                    continue
                for m in TOKEN_RE.findall(v.lower()):
                    tok_rows[norm_tok(m)].add((pt, i))
                    if c not in fkc or (pt, c) not in pre_cols:
                        tok_home[norm_tok(m)].add((pt, i))
    lost = []           # (table, column or None, n cells, reason)
    untracked = []
    for tname, t in pre["tables"].items():
        if not t["rows"]:
            continue
        k = kinds.get(tname, {})
        cols = t["cols"]
        own_dist = [j for j, c in enumerate(cols) if k.get(c) == "dist"]
        fk_cols = [j for j, c in enumerate(cols) if k.get(c) == "fk"]
        links = []
        rows_lost = 0
        for r in t["rows"]:
            ids = {norm_tok(m) for j in own_dist if r[j] is not None for m in TOKEN_RE.findall(r[j].lower())}
            if ids:
                L = set().union(*(tok_home.get(x, set()) for x in ids)) or \
                    set().union(*(tok_rows.get(x, set()) for x in ids))
            else:
                fids = {norm_tok(m) for j in fk_cols if r[j] is not None for m in TOKEN_RE.findall(r[j].lower())}
                lits = {norm(r[j]) for j in range(len(cols)) if j not in fk_cols and r[j] is not None
                        and len(norm(r[j])) >= 6 and not TS_RE.match(norm(r[j]))}
                if fids:
                    sets = [tok_rows.get(x, set()) for x in fids]
                    L = set.intersection(*sets)
                elif lits:              # a row a migration inserted (fixed values, no synthetic tokens)
                    L = set().union(*(cell_rows.get(x, set()) for x in lits))
                else:
                    links.append(None)
                    continue
            if not L:
                rows_lost += 1
            links.append(L)
        if rows_lost:
            lost.append((tname, None, rows_lost, "rows gone"))
        if any(l is None for l in links):
            untracked.append(tname)
        for j, c in enumerate(cols):
            kind = k.get(c, "low")
            vals = [(i, r[j]) for i, r in enumerate(t["rows"]) if r[j] is not None and links[i]]
            if not vals:
                continue
            if kind == "dist":
                gone, plain = 0, []
                for i, v in vals:
                    toks = [norm_tok(m) for m in TOKEN_RE.findall(v.lower())]
                    if not toks:
                        plain.append((i, v))      # a value a migration wrote: checked like a low-entropy one
                    elif not all(x in tok_rows for x in toks):
                        gone += 1
                if gone:
                    lost.append((tname, c, gone, "value gone"))
                vals = plain
                if not vals:
                    continue
            # low-entropy or FK column: some post column, aligned by row identity, must reproduce the values
            cand = defaultdict(int)
            for i, v in vals:
                nv = norm(v)
                hit = set()
                for (pt, pi) in links[i]:
                    for pj, pv in enumerate(post_cells[(pt, pi)]):
                        if pv == nv:
                            hit.add((pt, pj))
                for h in hit:
                    cand[h] += 1
            best = max(cand.values()) if cand else 0
            if best < len(vals):
                lost.append((tname, c, len(vals) - best, "value gone (aligned)"))
    return {"lost": bool(lost), "lost_detail": lost[:30], "untracked_tables": untracked}
