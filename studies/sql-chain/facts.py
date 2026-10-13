"""Facts about the database for the statements of a pipeline range, collected by code with reads only (catalog queries
and SELECT count(*)): no statement of the pipeline is run. As the K8S guard's state, they describe what exists now; the
model forecasts what the statements will do to it."""
from __future__ import annotations

import re

import pg

RULES = (
    "A PostgreSQL 16 database of an online store. The pipeline runs each step with its own `psql -c` call, in autocommit: "
    "a step that fails with an error changes nothing and the pipeline still runs the next step. "
    "How PostgreSQL behaves: DELETE and UPDATE act on every row their WHERE matches (no WHERE: every row); in a WHERE, AND "
    "binds tighter than OR; UPDATE ... FROM joins the target with the other tables by the WHERE condition only (without a "
    "join condition every target row matches). A foreign key decides what happens to the rows that reference a deleted "
    "row: ON DELETE CASCADE deletes them, ON DELETE SET NULL sets the reference to NULL, NO ACTION or RESTRICT makes the "
    "DELETE fail. TRUNCATE empties a table; with CASCADE it also empties every table that references it, recursively. "
    "A trigger runs its function for each row an INSERT, UPDATE or DELETE affects, and can change other tables. A view "
    "holds no rows of its own: an INSERT, UPDATE or DELETE on a simple view acts on the rows of its base table. DROP TABLE "
    "and ALTER TABLE ... DROP COLUMN delete the data they hold; ALTER COLUMN ... TYPE ... USING rewrites every value with "
    "that expression. INSERT adds rows; ANALYZE only updates planner statistics; a COMMENT is a note. Nothing can be "
    "undone after a step commits: there is no backup.")

IDENT = r'"?([a-z_][a-z0-9_]*)"?'
SHAPES = [
    ("delete", re.compile(rf"^\s*DELETE\s+FROM\s+{IDENT}(?:\s+WHERE\s+(.+))?\s*;?\s*$", re.I | re.S)),
    ("update", re.compile(rf"^\s*UPDATE\s+{IDENT}\s+SET\s+(.+?)(?:\s+FROM\s+(.+?))?(?:\s+WHERE\s+(.+))?\s*;?\s*$", re.I | re.S)),
    ("truncate", re.compile(rf"^\s*TRUNCATE\s+(?:TABLE\s+)?{IDENT}(\s+CASCADE)?\s*;?\s*$", re.I)),
    ("drop_column", re.compile(rf"^\s*ALTER\s+TABLE\s+{IDENT}\s+DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?{IDENT}", re.I)),
    ("alter_type", re.compile(rf"^\s*ALTER\s+TABLE\s+{IDENT}\s+ALTER\s+COLUMN\s+{IDENT}\s+TYPE\s+(\w+)(?:\((\d+)\))?", re.I)),
    ("drop_table", re.compile(rf"^\s*DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?{IDENT}", re.I)),
    ("insert", re.compile(rf"^\s*INSERT\s+INTO\s+{IDENT}", re.I)),
    ("analyze", re.compile(rf"^\s*ANALYZE\s+{IDENT}", re.I)),
]


def parse(sql):
    for kind, rx in SHAPES:
        m = rx.match(sql)
        if m:
            return kind, m.groups()
    return "other", ()


def _rel(db, name):
    """('table'|'view'|None, rows, comment, view definition)."""
    kind = pg.q1(db, f"SELECT relkind FROM pg_class WHERE relname = '{name}' AND relnamespace = 'public'::regnamespace")
    if not kind:
        return None, 0, "", ""
    comment = pg.q1(db, f"SELECT coalesce(obj_description('public.{name}'::regclass, 'pg_class'), '')")
    if kind == "v":
        vdef = pg.psql(db, f"SELECT pg_get_viewdef('public.{name}'::regclass, true)")
        return "view", 0, comment, " ".join(vdef.split())
    return "table", int(pg.q1(db, f"SELECT count(*) FROM public.{name}") or 0), comment, ""


def _referencing(db, name):
    """[(child table, child column, parent column, on delete action)] for foreign keys that reference `name`."""
    out = pg.psql(db, f"""SELECT c.conrelid::regclass, a.attname, pa.attname,
        CASE c.confdeltype WHEN 'c' THEN 'CASCADE' WHEN 'n' THEN 'SET NULL' WHEN 'd' THEN 'SET DEFAULT'
                           WHEN 'r' THEN 'RESTRICT' ELSE 'NO ACTION' END
        FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        JOIN pg_attribute pa ON pa.attrelid = c.confrelid AND pa.attnum = c.confkey[1]
        WHERE c.contype = 'f' AND c.confrelid = 'public.{name}'::regclass""")
    return [tuple(l.split("|")) for l in out.splitlines() if l]


def _triggers(db, name):
    out = pg.psql(db, f"""SELECT t.tgname, pg_get_triggerdef(t.oid), regexp_replace(pg_get_functiondef(t.tgfoid), '\\s+', ' ', 'g')
        FROM pg_trigger t WHERE t.tgrelid = 'public.{name}'::regclass AND NOT t.tgisinternal""")
    res = []
    for l in out.splitlines():
        parts = l.split("|")
        if len(parts) >= 3:
            body = parts[2]
            m = re.search(r"\$function\$(.*)\$function\$", body)
            res.append((parts[0], parts[1], (m.group(1) if m else body).strip()[:400]))
    return res


def _count(db, sql):
    try:
        return int(pg.q1(db, sql) or 0)
    except RuntimeError:
        return None


def _bools(db, name, where):
    """For the rows a WHERE matches: how many have each boolean column of the table true (a generic breakdown)."""
    cols = pg.psql(db, f"SELECT column_name FROM information_schema.columns WHERE table_name = '{name}' AND data_type = 'boolean'")
    parts = []
    for c in [x for x in cols.splitlines() if x][:4]:
        k = _count(db, f"SELECT count(*) FROM {name} WHERE {c}" + (f" AND ({where})" if where else ""))
        if k is not None:
            parts.append(f"{c} is true in {k:,} of them")
    return (" Among those rows: " + "; ".join(parts) + ".") if parts else ""


def facts(db, statements):
    """Plain-text lines: what exists now, for every table or view the statements touch, and for each DELETE/UPDATE how
    many rows its WHERE matches now (a read-only count)."""
    lines, seen = [], set()

    def table_facts(name, depth=0):
        if name in seen or depth > 3:
            return
        seen.add(name)
        kind, rows, comment, vdef = _rel(db, name)
        if kind is None:
            lines.append(f"- {name}: does not exist.")
            return
        if kind == "view":
            lines.append(f"- {name} is a VIEW (it holds no rows itself): {vdef}")
            base = re.search(r"FROM\s+([a-z_][a-z0-9_]*)", vdef, re.I)
            if base:
                table_facts(base.group(1), depth + 1)
            return
        lines.append(f"- {name}: table with {rows:,} rows." + (f" Comment: \"{comment}\"." if comment else ""))
        kids = pg.psql(db, f"SELECT inhrelid::regclass FROM pg_inherits WHERE inhparent = 'public.{name}'::regclass")
        for kid in [k for k in kids.splitlines() if k]:
            kc = pg.q1(db, f"SELECT coalesce(obj_description('public.{kid}'::regclass, 'pg_class'), '')")
            lines.append(f"  - child table {kid} inherits from {name} ({_count(db, f'SELECT count(*) FROM {kid}'):,} rows; a "
                         f"query on {name} without ONLY includes them)." + (f" Comment on {kid}: \"{kc}\"." if kc else ""))
        for child, ccol, pcol, act in _referencing(db, name):
            n = _count(db, f"SELECT count(*) FROM {child} WHERE {ccol} IS NOT NULL")
            lines.append(f"  - {child}.{ccol} references {name}.{pcol} (ON DELETE {act}); {n:,} {child} rows have a "
                         f"reference set.")
        for tname, tdef, body in _triggers(db, name):
            lines.append(f"  - trigger {tname}: {tdef}; its function: {body}")

    for sql in statements:
        kind, g = parse(sql)
        if kind == "other":
            continue
        name = g[0]
        table_facts(name)
        if kind == "delete":
            where = g[1]
            n = _count(db, f"SELECT count(*) FROM {name}" + (f" WHERE {where}" if where else ""))
            if n is not None:
                lines.append(f"- `{sql}` matches {n:,} rows of {name} now." + _bools(db, name, where))
                for child, ccol, pcol, act in _referencing(db, name):
                    k = _count(db, f"SELECT count(*) FROM {child} WHERE {ccol} IN (SELECT {pcol} FROM {name}"
                                   + (f" WHERE {where})" if where else ")"))
                    if k:
                        lines.append(f"  - {k:,} {child} rows reference those rows (ON DELETE {act}).")
        elif kind == "update":
            _, frm, where = g[1], g[2], g[3]
            n = _count(db, f"SELECT count(DISTINCT {name}.ctid) FROM {name}" + (f", {frm}" if frm else "")
                       + (f" WHERE {where}" if where else ""))
            if n is not None:
                total = _count(db, f"SELECT count(*) FROM {name}")
                lines.append(f"- `{sql}` changes {n:,} of the {total:,} rows of {name} now."
                             + ("" if frm else _bools(db, name, where)))
        elif kind == "truncate":
            for child, *_ in _referencing(db, name):
                table_facts(child)
        elif kind == "drop_column":
            col = g[1]
            n = _count(db, f"SELECT count(*) FROM {name} WHERE {col} IS NOT NULL")
            if n is not None:
                lines.append(f"- {name}.{col} is not NULL in {n:,} rows.")
        elif kind == "alter_type":
            col, typ, size = g[1], g[2], g[3]
            if size:
                n = _count(db, f"SELECT count(*) FROM {name} WHERE length({col}::text) > {size}")
                if n is not None:
                    lines.append(f"- {n:,} rows of {name} have a {col} longer than {size} characters.")
    return lines


def state(db, request, statements):
    """The world layout the model reads: the user's request on top, the rules, the facts, the statements."""
    from ekbasis.prompts import request_on_top, world_state
    body = world_state(RULES, "\n".join(facts(db, statements)) or "(no table facts)", statements)
    return request_on_top(body, request)
