# Pré-registro v2: o estado do produto (migration guard) contra a rodada v1

Versão 1.0, congelada em 2026-10-11, antes de qualquer chamada a modelo desta avaliação. O hash deste arquivo vai no
relatório ao líder. As hipóteses, populações, limiares e scripts não mudam depois dele. Desvios vão num adendo datado.

## 1. Pergunta

No estudo v1 (PREREG e20495c5…), a maior fraqueza foi esta: com regras de autocommit, quando a migração falhava, o modelo
ainda previa que o statement destrutivo tinha rodado (27 dos 61 alarmes falsos de perda). O produto
(`ekbasis migrate-check`, commit `24957b4` do branch `migration-guard`, PR #10) muda o estado em duas coisas:

1. **Regra transacional.** A regra do estado é a do executor real: um arquivo, uma transação; se falha, nada é aplicado.
   Os arquivos com `CONCURRENTLY`, `VACUUM`, `ALTER SYSTEM` ou com `BEGIN`/`COMMIT` próprios ficam em autocommit. São 60
   dos 582.
2. **Fatos de produção, não linhas.** O estado tem estatísticas do planner (linhas estimadas, fração de NULL, distintos)
   e mais nada sobre os dados: nenhuma linha de exemplo, nenhum valor, nenhuma contagem de literais.

Pergunta: com esse estado, o modelo corta os alarmes falsos em migrações que falham sem perder a qualidade geral?

## 2. Braços e rótulos

* **v1.** As respostas já existentes do estudo (`preds/ekbasis.jsonl` do estudo; nenhuma chamada nova).
* **A2, produto.** É o estado de `ekbasis.migrations.build_state` lido do banco semeado: catálogo pela consulta do
  produto e estatísticas depois de `ANALYZE`. As perguntas são as do produto: `lost` e `fails`, mais `half` nos
  arquivos em autocommit. O texto das perguntas é idêntico ao do estudo.
* **A1, ablação (exploratória).** É o estado v1, com linhas, fatos e contagens de literais, mas com o texto de regras
  do produto. Separa o efeito da regra do efeito de trocar linhas por estatísticas.
* **Execução.** O pipeline congelado do estudo rodou de novo e reexecutou as 599 migrações sorteadas. Os estados A1 e
  A2 saem **do mesmo banco semeado** que gera os rótulos desta rodada.
  * A semeadura não é bit a bit reprodutível (desvio 5 do estudo). Contra o estudo, o rótulo `lost` discorda em 2 itens
    e o `fails` em nenhum, nos dois regimes.
* **Rótulo primário (`label_product`).** É o rótulo do regime que o produto declara: o da rodada transacional nos
  arquivos em transação, o da rodada em autocommit nos demais. Fica em `data/labels_v2.jsonl`.
* **População.** Os 582 itens incluídos no estudo, todos também incluídos nesta rodada.
* **Estrato A** (n = 370, com 161 perdas): é a população de perda. A falha usa todos os 582 itens (64 falhas).

**Linhas de base, calculadas antes de qualquer chamada A1/A2, com `label_product`:**

| Braço | Pergunta | AUROC | P | R | F1 | ECE |
|---|---|---|---|---|---|---|
| v1 | perda, estrato A | 0,931 | 0,692 | 0,975 | 0,809 | 0,166 |
| v1 | falha, todos os itens | 0,963 | 0,587 | 0,844 | 0,692 | 0,063 |
| Regra R3 | perda, estrato A | — | 0,642 | 0,957 | 0,768 | — |
| Regra de falha | falha, todos os itens | — | — | — | 0,397 | — |

No estrato A, 45 migrações falham e não perdem dados. Nelas, o v1 dá alarme falso de perda em 36 (0,80) e a R3 em 35.

## 3. Arquivos congelados

| Arquivo | SHA-256 |
|---|---|
| `data/requests_a2.jsonl` | `e7f00aaa78f608752584c1317bc75547f1f1436a095f918d8423ad0c29ce0bc5` |
| `data/requests_a1.jsonl` | `854b7b685144ee61d1145cc6f5f15b4205296534667393bcf59fbf4615df9ebf` |
| `data/labels_v2.jsonl` | `82143ce6cb42bfa99d5a9e0cb89e7fa430248a23accd9b99eb963792e05ca519` |

Os hashes de `build_v2.py`, `convert_v2.py`, `run_v2.py` e `analysis_v2.py` estão em `MANIFEST_v2.sha256`.

## 4. Procedimento

* **API.** Hospedada (`https://openinterp.org/api/v1`), chave de estudo, **concorrência 1**, com Server-Timing gravado
  (fila e modelo separados). Cada requisição pode ser tentada até 3 vezes.
* **Ordem de execução.**
  1. Piloto de 10 itens do A2, para checar o encanamento. As respostas entram na análise, porque estado e perguntas
     não mudam.
  2. A2 completo.
  3. A1 completo.
* **Limiar** fixo em 0,5.
* **Erros.** Se um braço tiver mais de 2% de itens sem resposta, a análise roda nos itens respondidos por todos os
  braços e relata o número.

## 5. Hipóteses (confirmatórias, com rótulos `label_product`)

| | Hipótese | Critério de "passa" |
|---|---|---|
| H1 | Menos alarmes falsos de perda nas 45 migrações do estrato A que falham e não perdem dados | taxa do A2 ≤ 0,40, **e** menor que a do v1, **e** McNemar exato pareado p < 0,05 |
| H2 | Discriminação de perda (estrato A) | AUROC do A2 ≥ 0,90 **e** limite inferior do IC95 ≥ 0,85 |
| H3 | Melhor que a regex ciente de cópia (estrato A) | F1(A2) − F1(R3): limite inferior do IC95 pareado > 0 |
| H4 | Falha (todos os itens) | AUROC do A2 ≥ 0,90, limite inferior do IC ≥ 0,85, **e** F1(A2) − F1(regra) com limite inferior > 0 |
| H5 | Calibração de perda (estrato A) | ECE (10 faixas) ≤ 0,10 |
| H6 | Não inferior ao v1 em perda (estrato A) | AUROC(A2) − AUROC(v1): limite inferior do IC95 pareado > −0,03 |
| H7 | Verificação funcional da Action | Os 4 PRs do repositório e2e, rodados de novo no commit final, dão os vereditos esperados (#1 arriscado por perda, #2 arriscado por falha, #3 ok, #4 arriscado por código); 1 comentário por PR; a chave não aparece nos logs |

* **Intervalos.** Bootstrap de itens, 2.000 reamostragens, semente 20261010 (as funções do estudo).
* **Decisão: "produto pronto"** se H1, H2, H4, H6 e H7 passarem. H3 e H5 são registradas e relatadas, mas não
  bloqueiam.

**Exploratório:**
* o A1 contra o v1 e o A2, para decompor o efeito da regra e o efeito das estatísticas;
* a AUROC por regime (arquivos em transação ou em autocommit);
* os alarmes falsos em migrações limpas;
* a AUROC do v1 contra os rótulos da própria rodada;
* custo e latência.

## 6. Poder

* **H1.** 45 pares. Se a taxa cair de 0,80 para 0,40, os pares discordantes devem passar de 18. Um teste binomial com
  b ≈ 18 contra c ≈ 0 dá p < 0,001. Para efeitos pequenos (0,80 → 0,65), o teste é fraco.
* **H2 e H6.** O IC da AUROC tem meia-largura ≈ 0,03, como no estudo.

## 7. Ameaças

* **Estatísticas sintéticas.** Sobre 20 linhas, as estatísticas do planner são exatas. Em produção são estimativas. As
  colunas sintéticas são "all values distinct" em quase tudo, e dados reais têm mais repetição.
* **Contraste em dois eixos.** Sem linhas e sem contagens de literais, o A2 sabe menos que o v1 sobre UPDATE/DELETE com
  WHERE. H6 mede esse custo e o A1 o separa.
* **Rótulos.** Os rótulos desta rodada diferem do estudo em 2 itens. O v1 é avaliado contra os rótulos desta rodada (e,
  como referência, contra os do estudo).
* **Uso da API.** O mesmo modelo hospedado do estudo; outra carga pode dividir a fila.

sha256(MANIFEST_v2.sha256) = b0e6c5c86ae1c220a5f06ee8a1b923b667bc0bb2a8beda0351a113cf917c401d
