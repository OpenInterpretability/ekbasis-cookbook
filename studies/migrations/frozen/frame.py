"""Step 1 (text only, no execution): list every PostgreSQL migration of the source repos in apply order, and draw the
sample from the text alone, before any label exists.

Sampling frame (PREREG.md §3), three strata per repo, drawn uniformly at random with a fixed seed:
  A "destructive-looking": rule R2 (rules.py) matches (DROP TABLE/COLUMN/SCHEMA, TRUNCATE, DELETE, UPDATE, RENAME,
    ALTER COLUMN TYPE) - up to CAP_A;
  B "risky-looking": the broad RISKY pattern below matches but R2 does not (NOT NULL, constraints, unique indexes,
    DROP TYPE/VIEW...) - up to CAP_B;
  C "benign-looking": neither - up to CAP_C.
Size filter (before drawing): 1..MAX_STMTS statements and at most MAX_CHARS characters; the first migration of a repo
is never drawn (it runs on an empty database).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
from collections import Counter
import sys

import rules as RU
from sqlsplit import split_sql

ROOT = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(ROOT, "repos")
SEED = 20261010
CAP_A = 40
CAP_B = 15
CAP_C = 5
MAX_STMTS = 40
MAX_CHARS = 9000

RISKY = re.compile(r"\b(DROP\s+(TABLE|COLUMN|SCHEMA|TYPE|VIEW|MATERIALIZED)|ALTER\s+(TABLE|COLUMN)\b[^;]*\b(DROP|TYPE|SET\s+NOT\s+NULL|"
                   r"RENAME|ADD\s+CONSTRAINT|ADD\s+PRIMARY|ADD\s+UNIQUE)|TRUNCATE|DELETE\s+FROM|UPDATE\s+\S+\s+SET|"
                   r"CREATE\s+UNIQUE\s+INDEX|ALTER\s+TYPE|RENAME\s+TO|ADD\s+COLUMN[^;,]*NOT\s+NULL)",
                   re.I | re.S)

SOURCES = {
    # name: (github repo, how its migrations are laid out)
    "calcom": ("calcom/cal.com", "prisma", "packages/prisma/migrations"),
    "langfuse": ("langfuse/langfuse", "prisma", "packages/shared/prisma/migrations"),
    "triggerdev": ("triggerdotdev/trigger.dev", "prisma", "internal-packages/database/prisma/migrations"),
    "documenso": ("documenso/documenso", "prisma", "packages/prisma/migrations"),
    "formbricks": ("formbricks/formbricks", "prisma", "packages/database/migration"),
    "hoppscotch": ("hoppscotch/hoppscotch", "prisma", "packages/hoppscotch-backend/prisma/migrations"),
    "umami": ("umami-software/umami", "prisma", "prisma/migrations"),
    "lemmy": ("LemmyNet/lemmy", "diesel", "migrations"),
    "cratesio": ("rust-lang/crates.io", "diesel", "migrations"),
    "vaultwarden": ("dani-garcia/vaultwarden", "diesel", "migrations/postgresql"),
    "mattermost": ("mattermost/mattermost", "updown", "server/channels/db/migrations/postgres"),
    "kratos": ("ory/kratos", "pop", "persistence/sql/migrations/sql"),
}


def head_commit(name):
    return subprocess.run(["git", "-C", os.path.join(R, name), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def enumerate_repo(name):
    repo, layout, sub = SOURCES[name]
    d = os.path.join(R, name, sub)
    out = []
    if layout in ("prisma", "diesel"):
        fn = "migration.sql" if layout == "prisma" else "up.sql"
        for e in sorted(os.listdir(d)):
            p = os.path.join(d, e, fn)
            if os.path.isfile(p):
                out.append((e, os.path.join(sub, e, fn)))
    elif layout == "updown":
        for e in sorted(os.listdir(d)):
            if e.endswith(".up.sql"):
                out.append((e[:-7], os.path.join(sub, e)))
    elif layout == "pop":
        files = os.listdir(d)
        groups = {}
        for e in files:
            m = re.match(r"^(\d+)_([^.]+)\.(?:(\w+)\.)?(?:(autocommit)\.)?up\.sql$", e)
            if not m:
                continue
            ver, nm, dialect, auto = m.groups()
            if dialect in ("mysql", "sqlite3", "sqlite", "cockroach"):
                continue
            if dialect == "autocommit":
                dialect = None
            groups.setdefault((ver, nm), {})[dialect or "all"] = e
        for (ver, nm), g in sorted(groups.items()):
            e = g.get("postgres") or g.get("all")
            if e:
                out.append((f"{ver}_{nm}", os.path.join(sub, e)))
    return out


def main():
    frame, sample = [], []
    for name in SOURCES:
        migs = enumerate_repo(name)
        commit = head_commit(name)
        strata = {"A": [], "B": [], "C": []}
        for idx, (mid, rel) in enumerate(migs):
            text = open(os.path.join(R, name, rel), encoding="utf-8", errors="replace").read()
            stmts = split_sql(text)
            body = ";\n".join(stmts)
            ok_size = 1 <= len(stmts) <= MAX_STMTS and len(body) <= MAX_CHARS
            is_risky = bool(RISKY.search(body))
            stratum = "A" if RU.r2(stmts) else ("B" if is_risky else "C")
            rec = {"repo": name, "github": SOURCES[name][0], "commit": commit, "idx": idx, "mig": mid, "path": rel,
                   "n_stmts": len(stmts), "chars": len(body), "size_ok": ok_size, "risky_looking": is_risky, "stratum": stratum,
                   "sha256": hashlib.sha256(text.encode()).hexdigest()}
            frame.append(rec)
            if ok_size and idx > 0:            # the first migration of a repo runs on an empty database: nothing to lose
                strata[stratum].append(rec)
        rng = random.Random(f"{SEED}:{name}")    # one stream per repo, order-independent
        caps = {"A": CAP_A, "B": CAP_B, "C": CAP_C}
        pick = [r for k in "ABC" for r in rng.sample(strata[k], min(caps[k], len(strata[k])))]
        for r in pick:
            r["sampled"] = True
        sample += sorted(pick, key=lambda r: r["idx"])
        print(f"{name:12s} migrations={len(migs):4d} " + " ".join(f"{k}={len(v):4d}" for k, v in strata.items()) +
              f" sampled={len(pick)}",
              file=sys.stderr)
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "frame.jsonl"), "w") as f:
        for r in frame:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(ROOT, "data", "sample.jsonl"), "w") as f:
        for r in sample:
            f.write(json.dumps(r) + "\n")
    print(f"frame={len(frame)} sample={len(sample)} by stratum={dict(Counter(r['stratum'] for r in sample))}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
