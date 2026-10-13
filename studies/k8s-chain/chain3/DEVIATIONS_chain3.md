# Chain v3 deviations

- 2026-10-12T23:01:28Z, with 22 of 108 runs done and before any v3 number was read: `analyze_chain3.py` imported
  two helper functions from `../chain/analyze_chain.py`, whose module code runs the v1 analysis on import (it printed v1's
  numbers). The two functions (`binom_tail`, `wilcoxon_less`) are now copied verbatim into `analyze_chain3.py`; no
  metric, threshold or test changed. New hash: 90b473524e245be7.

## 2026-10-13 00:33 UTC — paralelismo 3 → 5 a pedido do Caio (depois de 57 execuções válidas gravadas; a troca efetiva foi às 00:33 UTC)

O pré-registro diz "até 3 em paralelo". O Caio pediu 5 para o estudo terminar antes (o braço do GLM leva ~8 min por
execução). As execuções em curso no momento da troca são interrompidas e refeitas do zero (o runner só grava execuções
completas). Risco: com mais execuções simultâneas, as chamadas aos dois previsores e o cluster kind local ficam mais
carregados, o que pode alongar os tempos medidos (H2) dos dois braços. A ordem embaralhada mistura os braços, então a
carga extra cai sobre os três. Análise de sensibilidade, decidida agora e antes de ler qualquer número posterior: para
cada previsor, a mediana de segundos por chamada nas execuções gravadas antes da troca contra depois dela. A H2 é
recalculada também só nas execuções anteriores à troca; as duas versões são relatadas.

## 2026-10-13 01:40 UTC — execuções do Ekbasis invalidadas por um erro meu no gateway (refeitas)

Das 00:57 às 01:29 UTC o gateway da API recusou com 400 as perguntas de tipo "boolean" (uma validação nova que só
aceitava noul/choice/score; o servidor aceita "boolean"). O braço chain_ekb deste estudo usa "boolean": 12 execuções
foram invalidadas como "queda do previsor" (nenhuma foi gravada como resultado; mais 2 cujas novas tentativas já estavam em curso quando a validação caiu, até 01:31 — 14 no total), e 3 delas (L_F10a, L_F3a, L_C2, semente
2) chegaram ao limite de 3 tentativas. A validação foi desligada às 01:29. Correção: as 14 invalidações dessa janela
(00:57–01:31:30 UTC) saem de `invalid_g.jsonl` para `invalid_g_gateway_bug.jsonl` (não contam como tentativas) e as execuções que faltam são
refeitas com o mesmo comando, depois que o runner em curso terminar. Os braços blind e chain_glm não chamam a API do
Ekbasis e não foram afetados.

## 2026-10-13 02:05 UTC — erro na cauda do teste de Wilcoxon (análise; lido depois dos números)

O `analyze_chain3.py` selado deu H2 e H3 "NÃO PASSA" com p = 1, com o Ekbasis abaixo do GLM em 32 dos 36 pares (os 4
restantes empatam em zero). A função `wilcoxon_less`, copiada de `../chain/analyze_chain.py`, tem a cauda invertida na
aproximação normal (n > 20 diferenças não nulas): devolve `0.5*erfc(-z/√2)` = P(W ≤ w) onde o teste unilateral pede
P(W ≥ w). O ramo exato (n ≤ 20) está certo. Este desvio foi escrito DEPOIS de ler os números, então a saída selada fica
como está (`results/analysis_g_sealed.txt`) e a versão corrigida é relatada ao lado, com duas verificações
independentes: SciPy `wilcoxon(alternative="less")` e um teste de permutação por troca de sinal (200.000 sorteios).
Os estudos anteriores com a mesma função: v1 H3 p = 0,863 selado → 0,137 corrigido (continua NÃO PASSA); v2 usou o
ramo exato (p = 0,0883, inalterado). Nenhuma conclusão anterior muda.
