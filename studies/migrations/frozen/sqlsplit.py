"""Split a PostgreSQL migration file into statements, with the comments outside string bodies removed.

Comments are stripped on purpose: Prisma writes "/* Warnings: ... All the data in the column will be lost */" into its
migrations, which would hand both the model and the rules the label's wording. Dollar-quoted bodies ($$ ... $$) are kept
verbatim (their comments are code).
"""
from __future__ import annotations

import re

DOLLAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")


def split_sql(text: str) -> list[str]:
    out, buf, i, n = [], [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "-" and text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and text.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if text.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif text.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            buf.append(" ")
            i = j
            continue
        if c == "'":
            esc = i > 0 and text[i - 1] in "eE" and (i < 2 or not (text[i - 2].isalnum() or text[i - 2] == "_"))
            j = i + 1
            while j < n:
                if esc and text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            buf.append(text[i:j + 1])
            i = j + 1
            continue
        if c == '"':
            j = text.find('"', i + 1)
            j = n - 1 if j < 0 else j
            buf.append(text[i:j + 1])
            i = j + 1
            continue
        if c == "$":
            m = DOLLAR.match(text, i)
            if m and not (i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_")):
                tag = m.group(0)
                j = text.find(tag, m.end())
                j = n if j < 0 else j + len(tag)
                buf.append(text[i:j])
                i = j
                continue
        if c == ";":
            s = "".join(buf).strip()
            if s:
                out.append(s)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    s = "".join(buf).strip()
    if s:
        out.append(s)
    # collapse runs of blank lines left by removed comments
    return [re.sub(r"\n\s*\n+", "\n", s) for s in out]
