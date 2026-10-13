"""The study's PostgreSQL (a Docker container): a seeded template database and one fresh copy per run.
Everything goes through `docker exec ... psql` (no client is installed on the host)."""
from __future__ import annotations

import os
import subprocess

CONTAINER = "ekb-sqlchain-pg"
DOCKER = "/usr/local/bin/docker"
TEMPLATE = "store_tmpl"
HERE = os.path.dirname(os.path.abspath(__file__))


def psql(db, sql, check=True, timeout=120):
    """Run SQL in db (autocommit, one psql -c per call unless sql has several statements). Returns stdout (unaligned)."""
    p = subprocess.run([DOCKER, "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", db, "-At", "-q",
                        "-v", "ON_ERROR_STOP=1"], input=sql, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"psql failed in {db}: {p.stderr.strip()[:400]}")
    return p.stdout.strip()


def q1(db, sql):
    """The first value of a query."""
    out = psql(db, sql)
    return out.splitlines()[0] if out else ""


def build_template():
    psql("postgres", f"DROP DATABASE IF EXISTS {TEMPLATE};")
    psql("postgres", f"CREATE DATABASE {TEMPLATE};")
    psql(TEMPLATE, open(os.path.join(HERE, "seed.sql")).read(), timeout=900)


def fresh(db):
    psql("postgres", f"DROP DATABASE IF EXISTS {db} WITH (FORCE);")
    psql("postgres", f"CREATE DATABASE {db} TEMPLATE {TEMPLATE};")


def drop(db):
    psql("postgres", f"DROP DATABASE IF EXISTS {db} WITH (FORCE);", check=False)


def psql_wrapper(db):
    """The `psql` the agent and pipeline.sh get: the run's database, nothing else."""
    return (f'#!/bin/bash\nexec {DOCKER} exec -i -e PGDATABASE={db} -e PGUSER=postgres {CONTAINER} psql "$@"\n')
