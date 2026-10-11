#!/bin/zsh
# Pausa a rodada entre 03:55 e 04:20 UTC (janela de manutenção agendada do servidor) e religa quando GLM e Ekbasis respondem.
# Sanitizado: diretório e chaves vêm do ambiente (GLM_BASE_URL, OPENAI_API_KEY, EKBASIS_API_KEY, EKBASIS_URL já exportados).
cd "$(dirname "$0")/.."
until (( 10#$(date -u +%H%M) >= 355 )); do sleep 20; done
PID=$(pgrep -f "[r]un.py plan.json full")
echo "$(date -u) pausa: matando PID $PID"
[ -n "$PID" ] && kill $PID; sleep 5; pgrep -f "[r]un.py plan.json full" && { echo "AINDA VIVO"; kill -9 $PID; }
.venv/bin/python ops/limpa_parcial.py full
until (( 10#$(date -u +%H%M) >= 420 )); do sleep 20; done
until .venv/bin/python ops/saude.py; do sleep 60; done
.venv/bin/python ops/saude.py || exit 1
echo "$(date -u) religando"
nohup ops/go.sh > /dev/null 2>&1 &
sleep 30; pgrep -f "[r]un.py plan.json full" && echo "religado ok" || echo "FALHA AO RELIGAR"
