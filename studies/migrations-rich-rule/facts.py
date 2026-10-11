"""The only door from the data to the rule (PREREG §3): the facts the Ekbasis 0.1.20 state shows, structured.

load(items_dir) drops label_tx, label_auto, empty_errors and seeded_rows before anything else.
view(raw, regime) -> Facts: tool, transaction, statements, schema_error, catalog, the replica statistics reduced to
what migrations.table_facts prints (regime R only), and the probes' facts and decision.
"""
from __future__ import annotations

import glob, json, os, sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "ekbasis"))
from ekbasis import migrations as M  # noqa: E402

KEEP = ("id", "repo", "path", "raw")


def load(items_dir: str) -> dict:
    out = {}
    for p in sorted(glob.glob(os.path.join(items_dir, "*.jsonl"))):
        for line in open(p):
            r = json.loads(line)
            out[r["id"]] = {k: r[k] for k in KEEP if k in r}
    return out


@dataclass
class ColStat:
    null_pct: float | None = None   # None: no NULL fact printed; 0.0 < x: "about x% NULL"; 0.001: "a few NULL"
    all_distinct: bool = False
    distinct: int | None = None     # printed only when <= 10


@dataclass
class TableStat:
    rows: int | None                # None: unknown (regime N or never analyzed)
    cols: dict = field(default_factory=dict)


@dataclass
class Facts:
    tool: str
    transaction: bool
    stmts: list
    flat: list                      # statements with bodies and literals blanked (migrations.outside_bodies)
    schema_error: str | None
    catalog: dict
    regime: str
    stats: dict | None              # {(schema, table): TableStat}; None in regime N
    probe_facts: list
    probe_decided: str | None

    def table_stat(self, t: dict) -> TableStat:
        if self.stats is None:
            return TableStat(rows=None)
        return self.stats.get((t["schema"], t["name"])) or TableStat(rows=None)


def _reduce(stats: dict, catalog: dict) -> dict:
    """Exactly the content of migrations.table_facts."""
    out = {}
    rows = stats.get("rows") or {}
    cols = stats.get("cols") or {}
    for t in catalog.get("tables") or []:
        key = f"{t['schema']}.{t['name']}"
        n = rows.get(key)
        ts = TableStat(rows=None if n is None or n < 0 else int(round(n)))
        for c in t["cols"] or []:
            s = cols.get(f"{key}.{c['name']}")
            if not s:
                continue
            nf, nd = s
            cs = ColStat()
            if nf and nf > 0:
                cs.null_pct = round(nf * 100) if nf >= 0.005 else 0.1
            if nd is not None and nd != 0 and n:
                dist = -nd * n if nd < 0 else nd
                if nd == -1:
                    cs.all_distinct = True
                elif dist <= 10:
                    cs.distinct = max(1, round(dist))
            if cs.null_pct is not None or cs.all_distinct or cs.distinct is not None:
                ts.cols[c["name"]] = cs
        out[(t["schema"], t["name"])] = ts
    return out


def view(raw: dict, regime: str) -> Facts:
    stmts = raw["statements"]
    pr = raw.get(f"probe_{regime}") or {"facts": [], "decided": None}
    return Facts(tool=raw["tool"], transaction=bool(raw["transaction"]), stmts=stmts,
                 flat=[M.outside_bodies(s) for s in stmts], schema_error=raw.get("schema_error"),
                 catalog=raw.get("catalog") or {}, regime=regime,
                 stats=_reduce(raw["stats"] or {}, raw.get("catalog") or {}) if regime == "R" and raw.get("stats")
                 else None,
                 probe_facts=list(pr.get("facts") or []), probe_decided=pr.get("decided"))
