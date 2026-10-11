#!/bin/zsh
# Sanitizado: diretório e chaves vêm do ambiente (GLM_BASE_URL, OPENAI_API_KEY, EKBASIS_API_KEY;
# EKBASIS_URL=https://openinterp.org/api/v1).
cd "$(dirname "$0")/.."
exec .venv/bin/python run.py plan.json full >> full_run.log 2>&1
