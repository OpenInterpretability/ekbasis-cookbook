# Desvios

- **D1 (12:41 UTC, frente 3, calibração):** relancei o `go_calib.sh` sem perceber que o primeiro processo já rodava
  (o `pgrep` saiu antes de o processo aparecer). Por ~20 s houve 2 processos de calibração (concorrência 2 no GLM) no
  mesmo primeiro item. Matei o segundo pelo PID. Se o item 1 tiver registro duplicado em `results.jsonl`, vale o
  primeiro registro de cada (cond, ataque, par).
- **D2 (13:18 UTC, frente 3, calibração):** o item 55/80 (travel user_task_11 × injection_task_1 ou o seguinte) ficou
  >17 min numa única requisição ao GLM (sem `max_tokens`, raciocínio desligado: geração longa/degenerada, com timeout
  de 600 s × 2 retentativas). Para não pesar na produção, matei o processo pelo PID, acrescentei `max_tokens=4096` às
  chamadas do agente (`run_agent.py`, `make_llm`) e retomei do item pendente. Os 54 itens já feitos não foram refeitos.
- **D3 (12:46–12:52 UTC, frentes 1 e 2, reinício do vLLM do Ekbasis, aviso do team-lead):** a rodada estática
  (12:41–14:02 UTC) atravessou a janela de reinício. Efeito: 2 HTTP 500 (12:46–12:48) no mesmo item, ambos refeitos
  pelo próprio runner (nenhuma resposta gravada com erro; nenhum `cannot_judge`), uma pausa de 95 s a partir de
  12:46:13 e 219 chamadas respondidas entre 12:47 e 12:52, com latência máxima de 5,9 s. Nenhum item foi descartado. O
  servidor depois do reinício deu os mesmos p: as 13 decisões do estudo oficial, refeitas no fim da rodada, reproduziram
  o p original com exatidão.
- **D4 (concorrência):** o team-lead liberou concorrência 3 no Ekbasis só por hoje, depois do reinício. Não usei: a
  rodada estática já tinha terminado em concorrência 1, e a frente 3 não rodou chamadas ao Ekbasis. Se a frente 3 paga
  for aprovada hoje, o juiz pode rodar em concorrência ≤ 3, e isso vai registrado aqui.
