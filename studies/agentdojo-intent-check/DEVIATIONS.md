# Desvios do PREREG.md (sha256 0633ae63…)

## D1 — pausa pela troca de perfil da B200 (registrado 2026-10-11 ~02:45 UTC, rodada em 2/~1191 execuções)
Aviso do líder: às 04:00 UTC o GLM e o Ekbasis reiniciam. Para que falha de infraestrutura não vire bloqueio da
defesa (o `IntentCheckToolsExecutor` bloqueia em `cannot_judge`) nem erro pontuado:
- `pausa.sh` mata o `run.py` às 03:55 UTC; `limpa_parcial.py` apaga as decisões do intent_check da execução
  interrompida (sem linha em results.jsonl), que é refeita do zero na retomada (o `run.py` é retomável e o AgentDojo
  refaz traces sem `utility`). Religa a partir de 04:20 UTC, só depois de `saude.py` passar (completion do GLM e um
  intent_check reais).
- Regra adicional, fixada antes de ver qualquer resultado pontuado: ao final, toda execução com `error` não nulo ou com
  alguma decisão `cannot_judge` é tratada como falha de infraestrutura — as linhas são removidas e a execução é refeita
  (até 2 vezes). Só o que continuar falhando depois disso é reportado como erro/bloqueio fail-closed, separadamente.

## D2 — correção de bug no analyze.py (registrado 2026-10-11, depois da rodada)
O `analyze.py` pré-registrado (sha256 8dee029a…, preservado como `analyze_prereg.py`) quebrava com `TypeError` no
`sorted()` do conjunto pareado: as chaves dos itens sem ataque têm `None` na posição da tarefa de injeção, e o Python
não compara `None` com `str`. A correção (sha256 ab0c752b…) muda só a chave de ordenação
(`key=lambda i: (i[0], i[1], i[2] or "")`); a ordenação não entra em nenhuma métrica, e o diff é de 1 linha.

## D3 — execução da pausa (D1)
`pausa.log`: o processo foi morto às 03:55:09 UTC; nenhuma decisão parcial precisou ser removida; a retomada foi às
04:20:37 UTC, depois de 2 checagens de saúde OK. No fim: 1.191/1.191 execuções, 0 erros e 0 `cannot_judge`, então a
regra de refazer não precisou ser aplicada.
