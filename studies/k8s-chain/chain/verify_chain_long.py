"""The chain study v2 (long pipelines): verify_chain.py with chain_tasks_long.py's tasks. Same arguments."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain_tasks_long as CTL  # noqa: E402
import verify_chain as M  # noqa: E402

M.CT = CTL
M.OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_long")
if hasattr(M, "RA"):
    M.RA.T = CTL
if __name__ == "__main__":
    M.main()
