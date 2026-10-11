#!/bin/zsh
cd "${0:A:h}"
export EKBASIS_API_KEY=$(cat ~/.config/ekbasis/study_api_key) EKBASIS_URL=https://openinterp.org/api/v1 PYTHONPATH=/tmp/ekbasis_pr
exec ../agentdojo_official/.venv/bin/python -W ignore run_static.py items.jsonl replay_items.jsonl static_out >> static_run.log 2>&1
