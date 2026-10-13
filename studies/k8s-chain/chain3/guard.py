#!/usr/bin/env python3
"""Entry point the run harness calls: the chain3 hook (guard_chain3.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guard_chain3  # noqa: E402

guard_chain3.GC.main()
