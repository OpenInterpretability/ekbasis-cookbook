"""Adapter for states in the CUT layout of 0.1.19+ (0.1.20 / 0.1.21: schema cut and code probes), which exist only as
text in the Rails v7 and P5 evaluations. Parses the text back into facts.Facts so the frozen rule reads what the model
read.

Layout (migrations._cut_state): the DDL of the touched tables; "Tables linked to them by a foreign key (their other
columns not shown): <neighbor>: <FK def> (<cols> NOT NULL), ...; <neighbor> (referenced by them)"; views; triggers with
function bodies; sequences; enums; domains; then "Rows:" lines for touched tables and neighbors; then "Facts: " with
the omitted-table count, the schema error (autocommit) and the probes' facts.

Neighbors become stub tables: their foreign-key columns only (NOT NULL as stated, type unknown) and their constraints.
Probe facts are split from the "Facts:" line at the probes' sentence starts.
"""
from __future__ import annotations

import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import facts as F                        # noqa: E402
from facts import ColStat, TableStat     # noqa: E402
from facts_v5 import Unconvertible, _col, _split_name   # noqa: E402
from ekbasis import migrations as M      # noqa: E402
from ekbasis import prompts as P         # noqa: E402

TABLE = re.compile(r"^CREATE TABLE (\S+) \($")
PROBE_START = re.compile(r"(?=Checked on a copy of the base schema: )|(?=Foreign key \S+ on \S+ references )"
                         r"|(?=Run on this schema with no rows, the migration fails: )")
TAIL_HEADS = ("Tables linked to them by a foreign key", "Views that depend on them:", "Triggers on them:",
              "Sequences: ", "Enum types: ", "Domains: ")


def _tables(lines: list, i: int, tables: list, oid: list) -> int:
    """Parses the DDL blocks starting at lines[i]; returns the index of the first line after them."""
    while i < len(lines):
        ln = lines[i]
        t = TABLE.match(ln)
        if t:
            schema, name = _split_name(t.group(1))
            items_, j = [], i + 1
            while j < len(lines) and lines[j] != ");":
                cl = lines[j]
                if re.match(r"^  \S", cl) and (not items_ or items_[-1].endswith(",")):
                    items_.append(cl)
                elif items_:
                    items_[-1] += "\n" + cl
                elif cl != "":
                    raise Unconvertible(f"unexpected line in a table: {cl!r}")
                j += 1
            if j >= len(lines):
                raise Unconvertible("unterminated CREATE TABLE")
            cols, cons = [], []
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
            oid[0] += 1
            tables.append({"oid": oid[0], "schema": schema, "name": name, "cols": cols, "cons": cons, "idx": [],
                           "stub": False})
            i = j + 1
            continue
        if ln.startswith("CREATE ") and "INDEX" in ln and tables:
            tables[-1]["idx"].append(ln.rstrip(";"))
            i += 1
            continue
        if ln.startswith("(none of the tables"):
            i += 1
            continue
        return i
    return i


def _neighbors(line: str, tables: list, oid: list):
    body = line.split(": ", 1)[1] if line.startswith("Tables linked") else line
    for part in body.split("; "):
        part = part.strip()
        m = re.match(r"^(\S+) \(referenced by them\)$", part)
        if m:
            schema, name = _split_name(m.group(1))
            oid[0] += 1
            tables.append({"oid": oid[0], "schema": schema, "name": name, "cols": [], "cons": [], "idx": [],
                           "stub": True})
            continue
        m = re.match(r"^(\S+): (FOREIGN KEY .*)$", part)
        if not m:
            raise Unconvertible(f"unparsed neighbor: {part[:80]!r}")
        schema, name = _split_name(m.group(1))
        cols, cons = {}, []
        for k, fk in enumerate(re.split(r", (?=FOREIGN KEY )", m.group(2))):
            nn = re.search(r" \(([^()]*) NOT NULL\)$", fk)
            if nn:
                fk = fk[: nn.start()]
            notnull = {c.strip() for c in nn.group(1).split(",")} if nn else set()
            fm = re.match(r"FOREIGN KEY \(([^)]*)\)", fk)
            if not fm:
                raise Unconvertible(f"unparsed foreign key: {fk[:80]!r}")
            for c in fm.group(1).split(","):
                c = c.strip().strip('"')
                cols[c] = {"name": c, "type": "", "notnull": c in notnull, "default": None, "generated": False,
                           "typname": ""}
            cons.append({"name": f"{name}_fk{k}", "type": "f", "def": fk, "ref": None})
        oid[0] += 1
        tables.append({"oid": oid[0], "schema": schema, "name": name, "cols": list(cols.values()), "cons": cons,
                       "idx": [], "stub": True})


def parse_cut_state(state: str) -> tuple:
    """(catalog, stats or None, probe facts, schema-error fact or None)."""
    m = re.search(r"\nCurrent state:\n(.*?)\n\nActions, in order:\n", state, re.S)
    if not m:
        raise Unconvertible("no 'Current state' block")
    cur = m.group(1)
    if not cur.startswith("Schema (the tables the migration touches"):
        raise Unconvertible("not the cut layout")
    head, sep, tail = cur.partition("\n\nRows:\n")
    if not sep:
        raise Unconvertible("no Rows block")
    lines = head.split("\n")
    tables, oid, enums = [], [1000], {}
    i = _tables(lines, 1, tables, oid)
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("Tables linked to them by a foreign key"):
            _neighbors(ln, tables, oid)
        elif ln.startswith("Enum types: "):
            for part in ln[len("Enum types: "):].split("; "):
                en, _, labs = part.partition(": ")
                enums[en] = re.findall(r"'((?:[^']|'')*)'", labs)
        # views, triggers (and their function bodies), sequences, domains: not read by the rule
        i += 1
    byname = {}
    for t in tables:
        byname.setdefault(t["name"], t)
    for t in tables:
        for k in t["cons"]:
            if k["type"] == "f":
                r = re.search(r"REFERENCES (\S+?)\(", k["def"])
                if r:
                    rn = r.group(1).split(".")[-1].strip('"')
                    if rn in byname:
                        k["ref"] = byname[rn]["oid"]
    rows_part, _, facts_part = ("\n" + tail).partition("\n\nFacts: ")   # no rows lines: "Rows:" then a blank
    stats, unknown = {}, 0
    for rl in rows_part.split("\n"):
        if not rl:
            continue
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
                raise Unconvertible(f"unparsed rows line: {rl[:80]!r}")
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
                        raise Unconvertible(f"unparsed column fact: {cf[:80]!r}")
                ts.cols[cn] = cs
        stats[(schema, name)] = ts
    if unknown and stats:
        raise Unconvertible("mixed regimes in one state")
    probe, schema_fact = [], None
    for s in [x.strip() for x in PROBE_START.split(facts_part) if x.strip()]:
        if s.startswith("Checked on a copy") or s.startswith("Foreign key "):
            probe.append(s)
        elif s.startswith("Run on this schema with no rows"):
            schema_fact = s
        elif not re.match(r"^\d+ other tables? omitted", s):
            raise Unconvertible(f"unparsed fact: {s[:80]!r}")
    return {"tables": tables, "enums": enums}, (stats if stats or not unknown else None), probe, schema_fact


def from_state(state: str, stmts: list, transaction: bool, schema_error, tool: str = "generic") -> F.Facts:
    if not stmts:
        raise Unconvertible("no statements")
    if ("\n\nActions, in order:\n" + P.numbered(stmts) + "\n") not in state:
        raise Unconvertible("the state's actions are not the split SQL")
    if (not state.startswith(M.RULES_AUTO)) != bool(transaction):
        raise Unconvertible("transaction mode differs from the state's rules")
    if "\nCurrent state:\nSchema (the tables the migration touches" in state:
        catalog, stats, probe, _ = parse_cut_state(state)
    else:                       # the cut could not be made: the state is the 0.1.17 "named" layout
        import facts_v5
        catalog, stats, flines = facts_v5.parse_state(state)
        probe = [x.strip() for fl in flines for x in PROBE_START.split(fl)
                 if x.strip().startswith(("Checked on a copy", "Foreign key "))]
    return F.Facts(tool=tool, transaction=bool(transaction), stmts=stmts, flat=[M.outside_bodies(s) for s in stmts],
                   schema_error=schema_error, catalog=catalog, regime="R" if stats is not None else "N", stats=stats,
                   probe_facts=probe, probe_decided=None)
