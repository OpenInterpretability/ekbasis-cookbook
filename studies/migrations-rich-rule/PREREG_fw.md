# Pré-registro 2: held-out em frameworks (v5 Django/Alembic, v6 Rails): regra, modelo e política de produto

Versão 1.0, 2026-10-11, escrita ANTES de abrir qualquer rótulo do v5 e do v6. O sha256 deste arquivo, do adaptador, das
regras e do script de pontuação vai ao líder antes da pontuação. Desvios vão para `DEVIATIONS_fw.md`.

**Exposição prévia, declarada.**
* Li o `PREREG_v5.md` para entender o formato. Ele traz contagens agregadas: Django 34 arriscadas em 242
  respondidas, Alembic 13 em 141, e os números da linha de base de linter.
* NÃO li rótulo por item, nem `results_v5.txt`, `results_v6.txt`, `README_v4_v5.md` ou o v7.
* O carregador (`load_fw.py`) descarta `label`, `lost_detail`, `run_error` e `seeded_rows` antes de qualquer outra
  coisa.

## 1. Pergunta
Num conjunto que nenhuma das regras viu (frameworks e projetos novos), com os mesmos fatos que o modelo leu:
1. a regra empata com o Ekbasis ou vence?
2. qual política de produto escolher?

## 2. Itens
* **v5:** `fw_eval5`, Django (saleor, babybuddy, paperless-ngx) e Alembic (MLflow, Superset).
* **v6:** `fw_eval_rails`, Rails (mastodon, maybe).
* **População:** os itens não excluídos que o produto **responde**, ou seja, todos menos os `code_not_foreseen`
  (mapeamento de `analysis_v5.product` / `analysis_v6.product`, sem mudança):
  * v5: Django 242, Alembic 141;
  * v6: Rails 138 enviados ao modelo, mais os `cannot_foresee_render` que não são falha de render offline.
* Os itens decididos em código pelo produto (`ok_empty`, `schema`, `cannot_foresee` que não é de código) recebem o
  mesmo veredito em TODOS os braços.

## 3. Fatos e adaptador (`facts_v5.py`)
O estado dessas avaliações (produto 0.1.15, layout "named": no máximo 8 tabelas, **sem probes**) existe só em texto.
O adaptador faz o parse dele (DDL, enums, linhas "Rows") para a mesma estrutura `Facts` que a regra recebe:
* probes vazios;
* catálogo só com as tabelas mostradas;
* regime pelo texto: todos os estados têm contagens, logo regime R.

Os statements são `split_sql(SQL renderizado)`, aceitos só se a lista de ações do estado for exatamente essa
numeração, e o modo de transação precisa bater com a regra do estado. Um item que o adaptador não converte sai dos
DOIS braços (condição do líder) e é relatado.

**Contagem antes dos rótulos:** 0 itens não convertidos (v5 278/278; v6 138/138).

**Validação sem rótulos** (`validate_v5_adapter.py`): renderizei o estado "named" a partir dos fatos brutos do v3 e
do D2, fiz o parse de volta e comparei.
* v3: colunas idênticas em 192/192 itens, e a predição da regra idêntica à dos fatos brutos em 192/192 (R e N, nas
  duas regras).
* D2: idêntica em 529/530.

## 4. Braços (congelados por hash antes dos rótulos)
* **(a) EKB:** as respostas gravadas (`fw_eval5/preds/v5.jsonl`, `fw_eval_rails/preds/v6.jsonl`; 0 erros) pelo
  veredito do produto, `analysis_v5.product`.
* **(b) R_RICH:** `rule.py` congelada (`f4c21f4d…`), sem mudança.
* **(c) R_NOSEED:** `rule_noseed.py` congelada (`285c87c9…`), sem mudança.
* **(d) Política:** R_NOSEED decide o veredito que falha o check. Quando o EKB diz arriscado (p ≥ 0,5 em lost ou
  fails, o limiar do produto) e a R_NOSEED diz ok, o item vira **AVISO** de revisão, que não falha o check.
* **(e) R_NOSEED OU EKB:** falha se um dos dois sinaliza. Motivo: o da R_NOSEED quando ela sinaliza, senão o do EKB.

Nos braços de regra: arriscado = erro de schema em autocommit, ou `fails`, ou `loses`. Motivo = fails (erro de schema
ou `fails`), senão loses. A verdade e o motivo exato seguem `analysis_v4.truth` e `ok_kind`.

## 5. Métricas
Por framework e agregado (v5 + v6, os três frameworks). O agregado é o **primário**.
* acurácia, recall, alarme falso e motivo exato do veredito que falha o check;
* na (d), também o **recall com avisos** (arriscadas que falham o check ou recebem aviso) e a taxa de aviso nas
  benignas;
* EKB contra R_NOSEED e EKB contra R_RICH: Δ de acurácia, IC 95% pareado por bootstrap (10.000 reamostragens, semente
  20261011, percentis) e McNemar exato bilateral;
* exploratório: os mesmos números só nos itens enviados ao modelo.

## 6. Critérios (decididos agora)
* **Regra × modelo (agregado), com o critério do estudo 1,** Δ = acc(EKB) − acc(R_NOSEED):
  * H1 "o modelo agrega" se Δ ≥ +2 pp e o limite inferior do IC > 0;
  * empate se −2 < Δ < +2;
  * "a regra é melhor" se Δ ≤ −2 pp;
  * senão, inconclusivo.
  O mesmo cálculo vale para R_RICH como secundário.
* **Escolha da política de produto** (agregado), entre (a), (c), (d) e (e). A (b) não é elegível, porque codifica a
  semeadura:
  1. elegível se alarme falso ≤ 15% **e** recall com avisos ≥ recall do EKB sozinho. Nas políticas sem aviso, o recall
     com avisos é o recall do veredito. O próprio EKB atende a segunda condição trivialmente;
  2. entre as elegíveis, vence a de maior acurácia do veredito. Empate (mesma acurácia) → maior recall com avisos →
     menos avisos nas benignas;
  3. se nenhuma for elegível, relato isso e qual chega mais perto, sem escolher.

## 7. Regras
Zero chamadas novas ao Ekbasis. Nada publicado, sem push, sem Modal. O v7 não é aberto.
