#!/usr/bin/env python3
"""Entry point the run harness calls: the v4 chain guard (../chain4/guard_chain4.py), unchanged."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "chain4"))
import guard_chain4  # noqa: E402

guard_chain4.GC.main()
