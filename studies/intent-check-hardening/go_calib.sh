#!/bin/zsh
cd "${0:A:h}"
export OPENAI_API_KEY=$(cat ~/.config/ekbasis/cb_glm_key) PYTHONPATH=/tmp/ekbasis_pr
exec ../agentdojo_official/.venv/bin/python -W ignore run_agent.py calib agent_plan.json calib_out >> calib_run.log 2>&1
