#!/bin/bash
# PREREG section 5 order, after the cold requests
cd "$(dirname "$0")"
P=venv/bin/python
while pgrep -f "[r]un_long.py data/req_cold" >/dev/null; do sleep 10; done
$P run_long.py data/req_L0.jsonl ans/L0.jsonl --conc 2 --go > logs_L0.txt 2>&1
$P run_long.py data/req_L0h.jsonl ans/L0h.jsonl --conc 2 --go > logs_L0h.txt 2>&1
$P run_long.py data/req_16k.jsonl ans/16k.jsonl --conc 2 --go > logs_16k.txt 2>&1
$P run_long.py data/req_32k.jsonl ans/32k.jsonl --conc 2 --go > logs_32k.txt 2>&1
$P run_long.py data/req_64k.jsonl ans/64k.jsonl --conc 1 --go > logs_64k.txt 2>&1
$P run_long.py data/req_120k.jsonl ans/120k.jsonl --conc 1 --ids data/order_120k.txt --go > logs_120k.txt 2>&1
echo DONE > logs_pipeline_done.txt
