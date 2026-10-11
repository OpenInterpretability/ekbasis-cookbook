#!/bin/sh
# A1 rebuild: start the three project containers, then build them in parallel with the rebased product.
PY=../../pr_study/.venv/bin/python
$PY harness7.py start redmine openproject consuldemocracy > start_a1.log 2>&1
for p in redmine openproject consuldemocracy; do
  $PY harness7.py build $p > build_a1_$p.log 2>&1 &
done
wait
echo done > rebuild_a1.done
