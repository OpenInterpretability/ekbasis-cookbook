# Adendo 1 (2026-10-11): sensibilidade sem as heurísticas da semeadura

Pedido do líder, recebido DEPOIS da pontuação. **Aviso de honestidade:** a pontuação do T2 já tinha rodado às ~20:57
UTC, então os rótulos do v3 e o resultado da regra congelada já estavam abertos quando este adendo foi escrito. A
análise é, portanto, **post hoc**. Para limitar o viés, a lista abaixo segue um critério único, fixado antes de rodar a
variante. Não escolhi heurística por heurística olhando o efeito no teste, e a variante não será ajustada depois de
rodar.

## Critério
Sai toda decisão da regra que resolve um fato que o estado NÃO mostra (os valores das linhas) assumindo o
comportamento do semeador: valores aleatórios, únicos, já em minúsculas, sem chaves JSON. Em cada ponto desses, a
variante R_RICH_NOSEED usa a leitura conservadora da documentação: o caso desconhecido **pode acontecer**, então conta
como risco. O resto da regra (simulação, transação, NULLs/linhas/distintos das estatísticas, casts) fica igual.

## O que sai (`rule.py` congelada → `rule_noseed.py`)
1. **Literal em coluna livre não casa** (`where_matches`, UPDATE). Agora um literal pode casar linhas em qualquer
   coluna (antes, só em enum, booleano ou coluna com ≤10 distintos).
2. **Deduplicação não acha duplicatas** (`DEDUPE`: ROW_NUMBER, HAVING count, NOT IN (SELECT min…)). Agora pode
   apagar ou alterar linhas.
3. **Condição com operador JSON não casa** (`->`, `?`, `@>`, `jsonb_`). Agora pode casar.
4. **Subquery que filtra por literal não casa.** Agora pode casar.
5. **Expressão que parte do próprio valor conta como "mantido"** (LOWER/UPPER/TRIM/BTRIM do próprio valor;
   REPLACE, jsonb_set, LEFT, array_append etc. aplicados à própria coluna; `col || …`, `col - …`). Agora conta como
   sobrescrita. Ficam como "mantido" só a identidade (`col = col`) e `COALESCE(col, …)`, porque a documentação garante
   que o valor não muda.
6. **Limiar de comprimento no encurtamento de varchar** (`n < 32`). Agora qualquer encurtamento pode falhar.

## O que fica, com o motivo
- No DELETE, um literal é tratado como presente: já é a leitura conservadora.
- Um literal numa coluna com FK pode não existir na tabela referenciada: conservador.
- Uma FK nova sobre valores existentes pode não casar: conservador.
- Um cast de texto para um tipo estrito pode falhar: conservador.
- A pigeonhole de UNIQUE e de enum: usa as contagens que o estado mostra.

## Relato
R_RICH (congelada, critério primário) e R_RICH_NOSEED lado a lado, em R e N, com as mesmas métricas, McNemar e
bootstrap. A conclusão para o produto usa a NOSEED, como pediu o líder.
