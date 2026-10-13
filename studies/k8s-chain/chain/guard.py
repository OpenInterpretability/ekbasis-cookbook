#!/usr/bin/env python3
"""Entry point the run harness calls (run_agent writes <HERE>/guard.py into the hook settings): the chain study's hook."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard_chain import main  # noqa: E402

main()
