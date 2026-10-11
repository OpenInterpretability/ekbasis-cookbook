"""Adapter for the framework evals (v5 Django/Alembic, v6 Rails): the Ekbasis state there exists only as TEXT (product
0.1.15, "named" layout: the tables the migration names and their foreign-key neighbors, at most 8; no probes). This
parses that text back into facts.Facts, so the frozen rule reads exactly what the model read.

from_state(state, sql, transaction, schema_error) -> Facts, or raises Unconvertible.
Statements: migrations.split_sql(rendered SQL), accepted only if the state's action list is exactly their numbering.
Probes: none (0.1.15 had none). Catalog: only the tables the state shows (synthetic oids; a foreign key's ref is the
shown table it names, else none). Statistics: the "Rows:" lines, the same content facts._reduce keeps; a state whose
tables all read "holds production data (row count unknown)" is regime N (stats None).
"""
from __future__ import annotations

import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import facts as F                       # noqa: E402
from facts import ColStat, TableStat    # noqa: E402
from ekbasis import migrations as M     # noqa: E402
from ekbasis import prompts as P        # noqa: E402


class Unconvertible(Exception):
    pass


TABLE = re.compile(r"^CREATE TABLE (\S+) \($")
TYPE_KW = re.compile(r" NOT NULL| DEFAULT | \(generated\)$")


def _col(line: str) -> dict:
    body = line.strip()
    body = body[:-1] if body.endswith(",") else body
    gen = body.endswith(" (generated)")
    if gen:
        body = body[: -len(" (generated)")]
    default = None
    if " DEFAULT " in body:
        body, default = body.split(" DEFAULT ", 1)
    notnull = body.endswith(" NOT NULL")
    if notnull:
        body = body[: -len(" NOT NULL")]
    name, _, typ = body.partition(" ")
    typ = typ.split("\n")[0] if default is None else typ
    if not typ:
        raise Unconvertible(f"column line without a type: {line!r}")
    b = M.disp  # noqa: F841  (layout reference: migrations.ddl)
    typname = re.sub(r"\(.*", "", typ).strip().strip('"')
    return {"name": name, "type": typ.strip(), "notnull": notnull, "default": default, "generated": gen,
            "typname": typname}


def _split_name(disp: str) -> tuple:
    if "." in disp and not disp.startswith('"'):
        s, n = disp.split(".", 1)
        return s, n
    return "public", disp


def parse_state(state: str) -> tuple:
    """(catalog, stats or None, other facts lines)."""
    m = re.search(r"\nCurrent state:\n(.*?)\n\nActions, in order:\n", state, re.S)
    if not m:
        raise Unconvertible("no 'Current state' block")
    cur = m.group(1)
    if not cur.startswith("Schema ("):
        raise Unconvertible("state does not start with the schema")
    lines = cur.split("\n")
    tables, i, oid = [], 1, 1000
    enums, rows_lines, facts_lines = {}, [], []
    section = "schema"
    while i < len(lines):
        ln = lines[i]
        if section == "schema":
            t = TABLE.match(ln)
            if t:
                schema, name = _split_name(t.group(1))
                cols, cons, j = [], [], i + 1
                items_ = []          # ddl() items: each starts with "  " after a line ending in ","
                while j < len(lines) and lines[j] != ");":
                    cl = lines[j]
                    if re.match(r"^  \S", cl) and (not items_ or items_[-1].endswith(",")):
                        items_.append(cl)
                    elif items_:
                        items_[-1] += "\n" + cl  # a multi-line DEFAULT or constraint
                    elif cl != "":
                        raise Unconvertible(f"unexpected line in a table: {cl!r}")
                    j += 1
                for cl in items_:
                    cm = re.match(r"^  CONSTRAINT (\S+) (.*?),?$", cl, re.S)
                    if cm:
                        d = cm.group(2)
                        typ = ("p" if d.startswith("PRIMARY KEY") else "u" if d.startswith("UNIQUE") else
                               "f" if d.startswith("FOREIGN KEY") else "c" if d.startswith("CHECK") else
                               "x" if d.startswith("EXCLUDE") else None)
                        if typ is None:
                            raise Unconvertible(f"unknown constraint: {cl!r}")
                        cons.append({"name": cm.group(1), "type": typ, "def": d, "ref": None})
                    else:
                        cols.append(_col(cl))
                if j >= len(lines):
                    raise Unconvertible("unterminated CREATE TABLE")
                oid += 1
                tables.append({"oid": oid, "schema": schema, "name": name, "cols": cols, "cons": cons, "idx": []})
                i = j + 1
                continue
            if ln.startswith("CREATE ") and "INDEX" in ln and tables:
                tables[-1]["idx"].append(ln.rstrip(";"))
                i += 1
                continue
            if ln.startswith("(none of the tables"):
                i += 1
                continue
            if ln.startswith("Enum types: "):
                for part in ln[len("Enum types: "):].split("; "):
                    en, _, labs = part.partition(": ")
                    enums[en] = re.findall(r"'((?:[^']|'')*)'", labs)
                i += 1
                continue
            if ln == "":
                section = "gap"
                i += 1
                continue
            raise Unconvertible(f"unexpected schema line: {ln!r}")
        if ln == "Rows:":
            section = "rows"
        elif ln.startswith("Other tables:") or ln.startswith("Tables linked") or ln.startswith("Views that"):
            section = "other"
        elif ln.startswith("Facts: "):
            facts_lines.append(ln[len("Facts: "):])
            section = "facts"
        elif section == "rows" and ln:
            rows_lines.append(ln)
        i += 1
    # foreign keys: ref = the shown table named in REFERENCES
    byname = {t["name"]: t for t in tables}
    for t in tables:
        for k in t["cons"]:
            if k["type"] == "f":
                r = re.search(r"REFERENCES (\S+?)\(", k["def"])
                if r:
                    rn = r.group(1).strip('"').split(".")[-1].strip('"')
                    if rn in byname:
                        k["ref"] = byname[rn]["oid"]
    stats, unknown = {}, 0
    for rl in rows_lines:
        name_part, _, rest = rl.partition(": ")
        schema, name = _split_name(name_part)
        if rest.startswith("holds production data"):
            unknown += 1
            continue
        if rest.startswith("row count unknown"):
            ts = TableStat(rows=None)
        elif rest.startswith("empty (0 rows)"):
            ts = TableStat(rows=0)
        else:
            mm = re.match(r"about ([\d,]+) rows", rest)
            if not mm:
                raise Unconvertible(f"unparsed rows line: {rl!r}")
            ts = TableStat(rows=int(mm.group(1).replace(",", "")))
        fm = re.search(r"; facts: (.*)$", rest)
        if fm:
            for cf in fm.group(1).split("; "):
                cn, _, desc = cf.partition(": ")
                cs = ColStat()
                for d in desc.split(", "):
                    if d == "a few NULL":
                        cs.null_pct = 0.1
                    elif re.fullmatch(r"about \d+% NULL", d):
                        cs.null_pct = int(re.search(r"\d+", d).group(0))
                    elif d == "all values distinct":
                        cs.all_distinct = True
                    elif re.fullmatch(r"about \d+ distinct values?", d):
                        cs.distinct = int(re.search(r"\d+", d).group(0))
                    else:
                        raise Unconvertible(f"unparsed column fact: {cf!r}")
                ts.cols[cn] = cs
        stats[(schema, name)] = ts
    if unknown and stats:
        raise Unconvertible("mixed regimes in one state")
    catalog = {"tables": tables, "enums": enums}
    return catalog, (stats if stats or not unknown else None), facts_lines


def from_state(state: str, sql: str, transaction: bool, schema_error, tool: str = "generic") -> F.Facts:
    stmts = M.split_sql(sql or "")
    if not stmts:
        raise Unconvertible("no statements")
    if ("\n\nActions, in order:\n" + P.numbered(stmts) + "\n") not in state:
        raise Unconvertible("the state's actions are not the split rendered SQL")
    tx_rule = state.startswith(M.RULES_AUTO) is False
    if tx_rule != bool(transaction):
        raise Unconvertible("transaction mode differs from the state's rules")
    catalog, stats, _ = parse_state(state)
    return F.Facts(tool=tool, transaction=bool(transaction), stmts=stmts, flat=[M.outside_bodies(s) for s in stmts],
                   schema_error=schema_error, catalog=catalog, regime="R" if stats is not None else "N", stats=stats,
                   probe_facts=[], probe_decided=None)
