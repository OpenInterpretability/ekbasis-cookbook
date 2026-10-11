#!/bin/zsh
cd "${0:A:h}"
export EKBASIS_API_KEY=$(cat ~/.config/ekbasis/study_api_key) EKBASIS_URL=https://openinterp.org/api/v1 PYTHONPATH=client
exec ../../agentdojo_official/.venv/bin/python -W ignore run_replay.py runs.jsonl out >> run.log 2>&1
