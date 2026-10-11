# PREREG — Calibração por cliente no Ekbasis

Escrito em 2026-10-11, antes de rodar qualquer análise com rótulos. Nenhuma chamada nova à API: o estudo usa só as
probabilidades já gravadas em estudos anteriores. `analysis.py` (congelado junto, hash em `PREREG.sha256`) implementa
exatamente o que está aqui; qualquer desvio vai para `DEVIATIONS.md`.

## Pergunta

Ajustar o limiar (ou recalibrar a probabilidade) **por cliente**, com os primeiros k feedbacks rotulados daquele
repositório, melhora as decisões em relação ao limiar global fixo de 0,5 que os produtos usam hoje? Com quantos
feedbacks o ganho aparece?

O que já sei antes de olhar (resultados agregados publicados): migrações v1 AUROC 0,948 (perda) e 0,963 (falha),
ECE 0,142 na perda; TS-Bench AgentDojo forte, AgentHarm/ASB com recall baixo (40%/48%) e precisão alta; a
recalibração genérica ajustada em AgentHarm+ASB piorou o AgentDojo. Não vi nenhum número por cliente nem por repositório.

## Clientes simulados (um cliente = um grupo × uma pergunta)

| Família | Fonte | Clientes | Pergunta(s) | Rótulo | Ordem dos feedbacks |
|---|---|---|---|---|---|
| M1 | cookbook `migrations/answers.jsonl` (582) | 12 repositórios | lost, fails | `label` (autocommit, o primário do estudo) | temporal (id ordena por data/número) |
| TS | cookbook `tsbench/answers.jsonl` (7.182) | agentharm, asb, agentdojo/{workspace, travel, slack, banking} | unsafe | estrito (≥0,5 → 1) | aleatória por trajetória, 20 sementes |
| M3 | cookbook `migrations/v3/answers_v3.jsonl` (184) | repositórios | lost, fails | `label_product` | temporal |
| M5 | scratchpad `fw_eval5` (278 respondidas) | 5 projetos Django/Alembic | lost, fails | `labels_v5` | aleatória, 20 sementes |

Os ids de trajetória do TS-Bench vêm do download público no commit `46358fa` (SHA-256 dos 9 arquivos conferido:
`e67381ea…3fed7`, igual ao do estudo).

**Excluídos:** `real_cases/` (63 incidentes, no máximo 8 por repositório e quase todos positivos por construção: não
formam clientes); `variant_answers` do TS-Bench (são perturbações dos mesmos itens).

## Desenvolvimento × teste (regra mecânica, fixada aqui)

Ordenar por `sha256("ekbasis-percliente-2026-10-11:" + nome)`:
- **Dev:** os 4 primeiros repositórios de M1 (hoppscotch, formbricks, langfuse, vaultwarden) e os 2 primeiros clientes
  do TS-Bench (agentdojo/banking, agentharm).
- **Teste primário:** os outros 8 repositórios de M1 (as duas perguntas) e os outros 4 clientes do TS-Bench
  (asb, agentdojo/workspace, travel, slack).
- **Secundário (só teste, nada escolhido nele):** M3 restrito aos repositórios de teste; M5 inteiro.

O dev serve só para escolher hiperparâmetros e o método primário. O teste roda **uma vez**, depois de
`selection.json` ser gravado e ter o hash registrado.

## Protocolo por cliente

Para k ∈ {5, 10, 20, 50}: os primeiros k feedbacks treinam; o resto do cliente avalia. Cliente só entra num k se
sobrarem ≥ 10 itens de avaliação. Temporal: um corte. Aleatório: 20 sementes fixas, sorteando trajetórias inteiras
(TS-Bench) para não vazar passos da mesma trajetória entre treino e avaliação; a métrica do cliente é a média das
sementes.

## Métodos (todos em logit; decisão = score ≥ 0,5)

- **G** (base): p ≥ 0,5.
- **A** (só limiar): limiar em logit que maximiza a acurácia no treino; empate → o mais perto de 0,5.
- **AR** (limiar com piso de recall): como A, mas o recall no treino não pode cair abaixo do de G; sem nenhum positivo
  no treino, o limiar não pode subir acima de 0,5.
- **C** (limiar com shrinkage): logit t = k/(k+k0) · logit t_A; k0 ∈ {10, 30, 100}.
- **B0** (só intercepto, a hipótese da "taxa-base"): q = σ(logit p + b), b ~ N(0, s²), MAP.
- **B** (Platt com prior no global): q = σ(a·logit p + b), a ~ N(1, (s/2)²), b ~ N(0, s²), MAP. s ∈ {0,25; 0,5; 1; 2}.

## Seleção no dev (k = 20, sem ruído)

- Melhor k0 de C, melhor s de B0 e de B pela média macro de Δacurácia.
- **Método primário de decisão** = o de maior Δacurácia média no dev entre {A, AR, C*, B0*, B*}.
- **Calibrador primário** = entre B0 e B (cada um com o seu s de menor Brier no dev), o de menor ΔBrier médio.

## Métricas

Por cliente, no conjunto de avaliação: acurácia, F1, recall, taxa de alarme falso (FP/negativos), Brier, ECE (10
faixas). Δ = método − G. Agregado: média macro (cada cliente-pergunta pesa igual). IC 95%: bootstrap percentil,
10.000 reamostras, sobre **unidades** (repositório; as duas perguntas de um repositório saem juntas; cada cliente
TS-Bench é uma unidade). Recall e alarme falso também agregados por soma de contagens (pooled).

Nota: transformações monotônicas por cliente não mudam o ranking dentro do cliente, então "alarme falso a recall fixo"
medido dentro do cliente é idêntico para todos os métodos. O que muda é o ponto de operação realizado: por isso
reporto recall e alarme falso realizados, e o método AR implementa o piso de recall.

## Ruído e adversário (salvaguarda)

Nos k feedbacks de treino, com sementes fixas (20 repetições nos clientes temporais):
- **flip:** 20% dos rótulos invertidos ao acaso (feedback ruidoso);
- **silence:** até 20% dos k rótulos, escolhidos entre os positivos, viram 0 (adversário que marca alertas reais
  como "false_alarm" para calar o guard).

## Hipóteses e critérios (teste primário, k = 20)

- **H1 (decisão):** Δacurácia do método primário com IC inferior > 0 **e** recall pooled não cai mais de 0,05 contra G.
- **H2 (calibração):** ΔBrier do calibrador primário com IC superior < 0.
- **S (salvaguarda), para cada método primário:** em flip e em silence, Δacurácia média ≥ −0,01 e queda de recall
  pooled ≤ 0,05; para o calibrador, também ΔBrier médio ≤ 0.
- **Passa para produto** se H1 e S do decisor passarem (limiar por cliente), ou H2 e S do calibrador (probabilidade
  exibida por cliente). Se nada passar, recomendo não construir.

Reportados sem critério: todos os k, todos os métodos, M3 e M5, e o menor k em que o IC de Δacurácia fica acima de 0.
Se o ganho só aparecer com k = 50, isso será dito como "> 20 feedbacks por repositório", e k > 50 não é testável aqui
(nenhum repositório de migração tem mais de 60 itens).
