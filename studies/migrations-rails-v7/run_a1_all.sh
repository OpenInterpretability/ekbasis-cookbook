#!/bin/sh
PY=../../pr_study/.venv/bin/python
cd eval && $PY run_v7.py --go > run_a1_test.log 2>&1
cd ../p5 && $PY run_p5.py --go > run_a1_p5.log 2>&1
echo done > ../run_a1.done
