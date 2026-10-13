#!/usr/bin/env python3
"""Entry point the run harness calls: the chain4 hook (guard_chain4.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard_chain4  # noqa: E402

guard_chain4.GC.main()
