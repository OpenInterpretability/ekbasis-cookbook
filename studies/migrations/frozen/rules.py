"""Baseline (a): regex rules over the migration's statements (comments already stripped). No model, no database.

lost:
  R1 (the usual linter list): DROP TABLE/COLUMN/SCHEMA, TRUNCATE, DELETE without WHERE, any RENAME.
  R2 (broad): R1 + any DELETE, any UPDATE ... SET, ALTER COLUMN ... TYPE.
  R3 (copy-aware): DROP COLUMN c / DROP TABLE t unless an earlier INSERT/UPDATE/CREATE TABLE AS statement names c or
     t (the data was moved first); TRUNCATE; DELETE (any); UPDATE of a column the migration did not add, unless the
     WHERE only fills NULLs; ALTER COLUMN ... TYPE ... USING.
fails:
  F1: SET NOT NULL; ADD COLUMN ... NOT NULL without DEFAULT; ADD CONSTRAINT UNIQUE/PRIMARY KEY/CHECK/FOREIGN KEY without
      NOT VALID; ADD PRIMARY KEY; CREATE UNIQUE INDEX; ALTER COLUMN ... TYPE.
half:
  H1: F1 and the migration has at least 2 statements.
"""
from __future__ import annotations

import re

I = re.I | re.S
ID = r'(?:"([^"]+)"|([A-Za-z_][\w$]*))'


def _ident(m, a=1):
    return (m.group(a) or m.group(a + 1) or "").lower()


DROP_TC = re.compile(r"\bDROP\s+(TABLE|COLUMN|SCHEMA)\b", I)
TRUNC = re.compile(r"\bTRUNCATE\b", I)
DELETE = re.compile(r"^\s*(?:WITH\b.*?\)\s*)?DELETE\s+FROM\b", I)
WHERE = re.compile(r"\bWHERE\b", I)
RENAME = re.compile(r"\bRENAME\b", I)
UPDATE = re.compile(r"^\s*(?:WITH\b.*?\)\s*)?UPDATE\s+(?:ONLY\s+)?" + ID, I)
ALTER_TYPE = re.compile(r"\bALTER\s+(?:COLUMN\s+)?" + ID + r"\s+(?:SET\s+DATA\s+)?TYPE\b", I)
USING = re.compile(r"\bUSING\b", I)

DROP_COL = re.compile(r"\bDROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?" + ID, I)
DROP_TAB = re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?((?:" + ID + r"\s*\.\s*)?" + ID + r"(?:\s*,\s*(?:" + ID +
                      r"\s*\.\s*)?" + ID + r")*)", I)
ADD_COL = re.compile(r"\bADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?" + ID, I)
SET_COLS = re.compile(r"\bSET\b(.*?)(?:\bFROM\b|\bWHERE\b|$)", I)
MOVES = re.compile(r"^\s*(?:WITH\b.*)?(INSERT\s+INTO|UPDATE|CREATE\s+TABLE\b.*\bAS\b|SELECT\b.*\bINTO\b)", I)

SET_NN = re.compile(r"\bSET\s+NOT\s+NULL\b", I)
ADD_NN = re.compile(r"\bADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?\S+\s+[^,]*?\bNOT\s+NULL\b[^,]*", I)
DEFAULT = re.compile(r"\bDEFAULT\b", I)
ADD_CONS = re.compile(r"\bADD\s+(?:CONSTRAINT\s+\S+\s+)?(UNIQUE|PRIMARY\s+KEY|CHECK|FOREIGN\s+KEY)\b", I)
NOT_VALID = re.compile(r"\bNOT\s+VALID\b", I)
UNIQUE_IDX = re.compile(r"\bCREATE\s+UNIQUE\s+INDEX\b", I)


def _names(text):
    return {(q or b).lower() for q, b in re.findall(r'"([^"]+)"|\b([A-Za-z_][\w$]*)\b', text)}


def r1(stmts):
    return any(DROP_TC.search(s) or TRUNC.search(s) or (DELETE.search(s) and not WHERE.search(s)) or RENAME.search(s)
               for s in stmts)


def r2(stmts):
    return r1(stmts) or any(DELETE.search(s) or UPDATE.search(s) or ALTER_TYPE.search(s) for s in stmts)


def r3(stmts):
    added = set()
    for i, s in enumerate(stmts):
        for m in ADD_COL.finditer(s):
            added.add(_ident(m))
        earlier_moves = [x for x in stmts[:i] if MOVES.search(x)]
        moved_names = set().union(*(_names(x) for x in earlier_moves)) if earlier_moves else set()
        for m in DROP_COL.finditer(s):
            if _ident(m) not in moved_names:
                return True
        m = DROP_TAB.search(s)
        if m:
            tabs = {n.split(".")[-1].strip().strip('"').lower() for n in m.group(1).split(",")}
            if not tabs <= moved_names:
                return True
        if TRUNC.search(s) or DELETE.search(s):
            return True
        if UPDATE.search(s):
            sm = SET_COLS.search(s)
            cols = {c.lower() for c in re.findall(r'"?([A-Za-z_][\w$]*)"?\s*=', sm.group(1))} if sm else set()
            where = s[WHERE.search(s).end():] if WHERE.search(s) else ""
            fills_nulls = bool(re.search(r"\bIS\s+NULL\b", where, I))
            if cols - added and not fills_nulls:
                return True
        if ALTER_TYPE.search(s) and USING.search(s):
            return True
    return False


def f1(stmts):
    for s in stmts:
        if SET_NN.search(s) or UNIQUE_IDX.search(s) or ALTER_TYPE.search(s):
            return True
        for m in ADD_NN.finditer(s):
            if not DEFAULT.search(m.group(0)):
                return True
        if ADD_CONS.search(s) and not NOT_VALID.search(s):
            return True
    return False


def h1(stmts):
    return f1(stmts) and len(stmts) >= 2


RULES = {"lost": {"R1": r1, "R2": r2, "R3": r3}, "fails": {"F1": f1}, "half": {"H1": h1}}
