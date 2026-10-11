"""The state Ekbasis (and the LLM judge) reads for one migration: built from the seeded database BEFORE the migration
runs, and from the migration's statements. Nothing from the execution run is read here (no label peeking).

Layout: ekbasis.prompts.world_state (the layout preflight.check_sql uses for SQL): rules, "Current state:", the
statements as numbered actions, and the note that the questions are about the state after all of them.
"""
from __future__ import annotations

import re

from psycopg import sql as S

import pgexec as X

MAX_TABLES = 8
SAMPLE_ROWS = 2
SOFT_CHARS = 14000          # ~4k tokens: shrink the state until it fits
HARD_TOKENS = 8000          # estimated tokens above which the item is excluded (PREREG §4)
VAL_CHARS = 40
MAX_LIT_FACTS = 10
LIT_CMP = re.compile(r'(?:"([^"]+)"|\b([A-Za-z_]\w*))\s*(=|!=|<>|\bIN\s*\(|\bNOT\s+IN\s*\()\s*'
                     r"((?:'(?:[^']|'')*'\s*,?\s*)+)", re.I)

WORLD_NOTE = "The questions are about the state after all these actions."

RULES = ("A PostgreSQL 16 database used by a running application. The statements of one migration run in order, each "
         "in autocommit mode (each statement commits on its own; BEGIN opens a transaction that COMMIT ends); a "
         "statement that fails (an error or a constraint violation) changes nothing and the next one still runs.")

# Frozen questions (PREREG §2). Wording follows ekbasis.shell.SHELL_LOST / preflight.sql_fails.
Q_LOST = {"type": "noul", "instructions": (
    "Does this migration permanently lose any data: a non-NULL value that is stored in some row before and afterwards "
    "is in no table at all (a deleted row, a dropped table or column whose values were not copied elsewhere, a value "
    "overwritten, or a value changed by a type conversion)? Values that were copied or moved to another column or "
    "table are not lost, and renaming a table or column loses nothing.")}
Q_FAILS = {"type": "noul", "instructions": (
    "Does any statement of this migration fail (end with an error or a constraint violation) on this database?")}
Q_HALF = {"type": "noul", "instructions": (
    "Is this migration left half applied: some statement fails while the statements that do not fail still change "
    "the schema or the data?")}
QUESTIONS = {"lost": Q_LOST, "fails": Q_FAILS, "half": Q_HALF}


def sql_fails(k: int) -> dict:  # exploratory, per statement (preflight wording)
    return {"type": "noul", "instructions": f"Does statement {k} fail (an error or a constraint violation, so it changes nothing)?"}


def numbered(lines):
    return "\n".join(f"{i + 1}. {x}" for i, x in enumerate(lines))


def world_state(rules, state, actions):
    return f"{rules}\n\nCurrent state:\n{state}\n\nActions, in order:\n{numbered(actions)}\n\n{WORLD_NOTE}"


def _named(text: str, tables: list) -> list:
    return [t for t in tables if re.search(r"(?<![\w$])[\"'`]?" + re.escape(t["name"]) + r"[\"'`]?(?![\w$])", text,
                                           re.I)]


def _lit(v):
    if v is None:
        return "NULL"
    s = str(v)
    if len(s) > VAL_CHARS:
        s = s[:VAL_CHARS] + "..."
    return "'" + s.replace("'", "''") + "'"


def _ddl(t, cat):
    lines = []
    for c in t["cols"]:
        d = f"  {c['name']} {c['type']}"
        if c["notnull"]:
            d += " NOT NULL"
        if c["default"]:
            d += f" DEFAULT {c['default']}"
        if c["generated"]:
            d += " (generated)"
        lines.append(d)
    for k in t["cons"]:
        if k["type"] in ("p", "u", "c", "f", "x"):
            lines.append(f"  CONSTRAINT {k['name']} {k['def']}")
    out = f"CREATE TABLE {X.disp(t)} (\n" + ",\n".join(lines) + "\n);"
    idx = [i["def"] for i in t["idx"] if not i["primary"] and not any(
        k["name"] in i["def"] for k in t["cons"] if k["type"] in ("u", "p", "x"))]
    if idx:
        out += "\n" + "\n".join(i + ";" for i in idx)
    return out


def _facts(con, t) -> tuple:
    q = X.qname(t)
    n = con.execute(S.SQL("SELECT count(*) FROM {}").format(q)).fetchone()[0]
    facts = []
    for c in t["cols"]:
        qc = S.Identifier(c["name"])
        nn, nd, maxlen = con.execute(S.SQL("SELECT count({c}), count(DISTINCT {c}::text), max(length({c}::text)) FROM {t}")
                                     .format(c=qc, t=q)).fetchone()
        f = []
        if n - nn:
            f.append(f"{n - nn} NULL")
        if nn and nd < nn:
            f.append(f"{nn - nd} repeated values")
        if nn and nd <= 4 and c["base"] not in X.TEXT | {"uuid"}:
            vc = con.execute(S.SQL("SELECT {c}::text, count(*) FROM {t} WHERE {c} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1")
                             .format(c=qc, t=q)).fetchall()
            f.append("values " + ", ".join(f"{_lit(v)} x{k}" for v, k in vc))
        if nn and c["base"] in X.TEXT:
            f.append(f"longest {maxlen} characters")
        if f:
            facts.append(f"{c['name']}: " + ", ".join(f))
    return n, facts


def build_state(db: str, stmts: list) -> dict:
    """{'prompt': text, 'shown': [...], 'est_tokens': int, 'level': shrink level used} for the seeded database db."""
    with X.connect(db) as con:
        cat = X.catalog(con)
        tables = [t for t in cat["tables"].values() if not t["ispart"]]
        byoid = {t["oid"]: t for t in tables}
        text = "\n".join(stmts)
        named = _named(text, tables)
        partners = []
        for t in tables:
            for k in t["cons"]:
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
        shown = shown[:MAX_TABLES]
        used_types = {c["typname"].lstrip("_") for t in shown for c in t["cols"]}
        enum_lines = [f"{e}: " + ", ".join(_lit(v) for v in labels) for e, labels in cat["enums"].items()
                      if e in used_types or re.search(r"(?<![\w$])\"?" + re.escape(e) + r"\"?(?![\w$])", text)]
        rows, info = {}, {}
        for t in shown:
            n, facts = _facts(con, t)
            cols = [c["name"] for c in t["cols"]]
            sample = con.execute(S.SQL("SELECT {} FROM {} LIMIT {}").format(
                S.SQL(", ").join(S.SQL("{}::text").format(S.Identifier(c)) for c in cols), X.qname(t),
                S.Literal(SAMPLE_ROWS))).fetchall() if cols else []
            info[t["oid"]] = (n, facts, sample)
        # rows matching the literals the statements compare columns with (WHERE slug = 'x', id IN ('a', 'b')): a
        # query a guard can run before the migration, and often the fact that decides an UPDATE or a DELETE
        lit_facts = []
        for m in LIT_CMP.finditer(text):
            col = m.group(1) or m.group(2)
            lits = re.findall(r"'((?:[^']|'')*)'", m.group(4))[:20]
            for t in shown:
                if col not in [c["name"] for c in t["cols"]] or len(lit_facts) >= MAX_LIT_FACTS:
                    continue
                try:
                    n = con.execute(S.SQL("SELECT count(*) FROM {} WHERE {}::text = ANY(%s)").format(
                        X.qname(t), S.Identifier(col)), ([x.replace("''", "'") for x in lits],)).fetchone()[0]
                except Exception:
                    continue
                shown_l = ", ".join(_lit(x.replace("''", "'")) for x in lits[:4]) + (", ..." if len(lits) > 4 else "")
                f = (f"{X.disp(t)}.{col} = {shown_l}" if len(lits) == 1 else f"{X.disp(t)}.{col} IN ({shown_l})") + \
                    f": {n} row{'s' if n != 1 else ''}"
                if f not in lit_facts:
                    lit_facts.append(f)
        others = []
        for t in tables:
            if t in shown:
                continue
            n = con.execute(S.SQL("SELECT count(*) FROM {}").format(X.qname(t))).fetchone()[0]
            others.append(f"{X.disp(t)} ({n} rows)")

    def render(level):
        # level 0: everything; 1: one sample row; 2: no sample rows; 3: partners reduced to a row count;
        # 4: no per-column facts for partners
        keep = shown if level < 3 else named[:MAX_TABLES] or shown[:1]
        dropped = [t for t in shown if t not in keep]
        parts = ["Schema (the tables the migration names, and the tables linked to them by foreign keys):"]
        parts += [_ddl(t, cat) for t in keep]
        if enum_lines:
            parts.append("Enum types: " + "; ".join(enum_lines))
        parts += ["", "Rows:"]
        for t in keep:
            n, facts, sample = info[t["oid"]]
            k = {0: SAMPLE_ROWS, 1: 1}.get(level, 0)
            line = f"{X.disp(t)}: {n} row{'s' if n != 1 else ''}"
            if k and sample:
                line += f"; the first {min(k, len(sample))}: " + "; ".join(
                    "(" + ", ".join(_lit(v) for v in r) + ")" for r in sample[:k])
            if facts:
                line += "; facts: " + "; ".join(facts)
            parts.append(line)
        if lit_facts:
            parts.append("Rows matching values the statements compare with: " + "; ".join(lit_facts))
        rest = [f"{X.disp(t)} ({info[t['oid']][0]} rows)" for t in dropped] + others
        if rest:
            parts.append("Other tables (rows not shown): " + ", ".join(rest[:40]) + (", ..." if len(rest) > 40 else ""))
        return world_state(RULES, "\n".join(parts), stmts)

    level, prompt = 0, render(0)
    while len(prompt) > SOFT_CHARS and level < 3:
        level += 1
        prompt = render(level)
    est = int(len(prompt) / 3.2)
    return {"prompt": prompt, "shown": [X.disp(t) for t in shown], "named": [X.disp(t) for t in named],
            "est_tokens": est, "level": level}
