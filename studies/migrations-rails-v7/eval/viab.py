"""Viability check before sampling: does the project's full history replay from an empty database?"""
import sys, time
import harness7 as H7
H = H7.H
name = sys.argv[1]
plan = H.inner(name, None, "plan")
nodes = [r["node"] for r in plan]
db = f"viab_{name}"
H.create_role_db(db)
t = time.time()
res = H.inner(name, db, "apply", nodes)
print(name, "migrations", len(nodes), "applied", len(res["done"]), "failed", res["failed"], (res["error"] or "")[:400],
      f"{time.time() - t:.0f}s", flush=True)
H.X.drop_db(db)
