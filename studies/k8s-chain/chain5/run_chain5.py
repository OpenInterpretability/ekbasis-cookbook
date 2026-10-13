"""Chain study v5 runner (another agent): v4 (../chain4) with Claude Sonnet 5.5 as the agent; this folder's hook = the v4 guard.
    EKBASIS_URL=... EKBASIS_API_KEY=... python3 run_chain5.py --prefix s --agent sonnet55 --conds blind chain_ekb --seeds 1 2 --parallel 5"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "chain"))
import chain_tasks_long as CTL  # noqa: E402
import run_chain as M  # noqa: E402

M.CT = CTL
M.RA.T = CTL
M.RA.HERE = HERE                                   # the hook: <chain3>/guard.py
M.RA.RUNS = os.path.join(M.kube.K8S_TMP, "chain5runs")
M.RA.AGENTS["sonnet55"] = ("claude-sonnet-5-5", {})
M.RES = os.path.join(HERE, "results")
_orig_run_once = M.RA.run_once


def run_once(*a, **k):
    """A forecaster that answered but gave no usable answer (GLM: unparsable output) is a result of the arm, not an
    outage: the run stays valid. Only infrastructure errors invalidate it, as in Phase 1."""
    row, invalid = _orig_run_once(*a, **k)
    if invalid == "forecaster outage":
        errs = [g.get("forecaster_error", "") for g in row.get("guard") or [] if g.get("forecaster_error")]
        if errs and all("unparsable" in e for e in errs):
            invalid = None
    return row, invalid


M.RA.run_once = run_once
if __name__ == "__main__":
    M.main()
