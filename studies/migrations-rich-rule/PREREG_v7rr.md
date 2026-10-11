# Pré-registro 3: a política (d) contra o produto atual (0.1.21) no Rails v7 (held-out) e no P5 (dev)

Versão 1.0, 2026-10-11, escrita ANTES de abrir os rótulos do Rails v7. O sha256 deste arquivo, do adaptador, das
regras e dos scripts vai a main antes da pontuação. Desvios vão para `DEVIATIONS_v7rr.md`.

## Exposição prévia, declarada
* Li o `ADDENDUM_A1.md` do v7 para entender o desenho. Ele traz agregados do rótulo:
  * 307 respondidas, 119 arriscadas (115 perdem, 4 falham), 188 benignas;
  * entre os 300 enviados ao modelo, 216 são só-esquema (110 perdem, 106 ok) e 84 não (77 ok, 5 perdem, 2 falham);
  * a linha de base R3∨F1.
* NÃO li rótulo por item, nem `eval/results_a1.txt`, `p5/results_a1.txt`, `discarded_stale/` ou o PREREG_v7 além do
  necessário.
* Calculei os vereditos do EKB (`ekb_v7.py`) e a conversão dos estados, sem rótulos.

## 1. Pergunta
Contra o produto atual (0.1.21: corte de schema, probes e regra só-esquema), a política (d) ("R_NOSEED decide; EKB
acima do limiar vira aviso de revisão") continua a escolha certa pelo critério do held-out anterior?

## 2. Dados
* **Primário, held-out:** Rails v7 adendo A1 (`fw_eval_rails7/eval`), projetos consuldemocracy, openproject e
  redmine.
  * População: os itens não excluídos que o produto responde (todos menos `code_not_foreseen`), cerca de 307.
  * As respostas gravadas (`eval/preds/v7.jsonl`) passam pelo veredito do produto 0.1.21, `analysis_v7.product`, que
    inclui as probes decididas em código e a regra só-esquema (p_fail = 0 em plano só-esquema).
  * Rótulos: o campo `label` dos itens, por execução.
* **Sensibilidade, dev** (já vi o v3): P5, as 184 do v3 com estados 0.1.20/0.1.21 (`p5/`).
  * Veredito do EKB: o NEW de `analysis_p5.py` (probe_fails → fails; `analysis_v3.product_verdict`; regra
    só-esquema).
  * Rótulos: `p5/data/labels_v3.jsonl`.
  * Statements para a regra: os do p2 (mesmos ids).
  * Itens com `state_same` falso ficam fora (o A1 relata 0).

## 3. Fatos e adaptador (`facts_cut.py`)
Os estados existem só em texto, no layout cortado: DDL das tabelas tocadas; vizinhos por FK numa linha; views,
triggers, sequências, enums e domínios; "Rows"; "Facts" com a contagem de omitidas, o erro de schema e os fatos das
probes. O adaptador faz o parse para a estrutura de fatos:
* vizinhos viram tabelas-esboço, só com as colunas de FK (NOT NULL conforme a linha) e as constraints;
* os fatos das probes vão para `probe_facts`;
* views, triggers e sequências não são lidos (a regra não os usa);
* se o corte não foi possível, o estado tem o layout "named" e cai no `facts_v5`.

Statements = `split_sql(SQL renderizado)`, aceitos só se a lista de ações do estado for exatamente essa numeração.
Item não convertido sai de TODOS os braços e é relatado.

**Conversão antes dos rótulos:**
* Rails v7: 300/300 convertidos, todos no layout cortado, nenhum com fato de probe;
* P5: 190/190;
* 7 itens do v7 são decididos em código (probes 2, esquema 2, vazio 3) e recebem o veredito do produto em todos os
  braços.

**Validação sem rótulos** (`validate_cut_adapter.py`): renderizei o estado 0.1.20 (`build_state`, com o corte) a
partir dos fatos brutos, com o catálogo do corte_schema, que tem dependências, e os fatos de probe do p2; depois fiz
o parse de volta.

| Conjunto | Estados cortados (R) | Fatos de probe idênticos | Predição das duas regras idêntica à dos fatos brutos |
|---|---|---|---|
| v3 | 188 | 190/190 | 190/190 em R, 192/192 em N |
| D2 | 523 | 526/526 | 526/526 em R, 530/530 em N |

**Achado lateral:** os itens do p2 (`p2/data/items_p2`) não têm informação de dependência no catálogo, então os
estados "0.1.20" do p2 saíram no layout "named", SEM corte. Isso não afeta este estudo, mas vai relatado a main.

## 4. Braços (os do held-out anterior, código congelado sem mudança)
* **(a) EKB:** veredito do produto 0.1.21, como acima.
* **(b) R_RICH:** `rule.py` (`f4c21f4d…`). Só relatada; não é candidata.
* **(c) R_NOSEED:** `rule_noseed.py` (`285c87c9…`).
* **(d) Política:** R_NOSEED decide o veredito que falha o check. Se o veredito do EKB é arriscado e a R_NOSEED diz ok
  (só em itens enviados ao modelo), o item vira AVISO.
* **(e) R_NOSEED OU EKB.**

Nos braços de regra: arriscado = erro de schema em autocommit, ou `fails`, ou `loses`; motivo = fails, senão loses.
Itens decididos em código pelo produto recebem o mesmo veredito em todos os braços.

## 5. Métricas
As do held-out anterior, com o mesmo código (`score_fw.stats` e `score_fw.compare`):
* acurácia, recall, alarme falso e motivo exato;
* na (d), recall com avisos e avisos nas benignas;
* EKB contra R_NOSEED e contra R_RICH: Δ, IC 95% pareado por bootstrap (10.000 reamostragens, semente 20261011) e
  McNemar exato bilateral;
* exploratório: os mesmos números só nos itens enviados ao modelo.

## 6. Critérios (os mesmos)
* **Regra × modelo no Rails v7,** Δ = acc(EKB) − acc(R_NOSEED):
  * H1 se Δ ≥ +2 pp e o limite inferior do IC > 0;
  * empate se −2 < Δ < +2;
  * "a regra é melhor" se Δ ≤ −2;
  * senão, inconclusivo.
* **Política (Rails v7)**, entre (a), (c), (d) e (e):
  1. elegível se alarme falso ≤ 15% e recall com avisos ≥ recall do EKB;
  2. vence a de maior acurácia do veredito; empate → maior recall com avisos → menos avisos nas benignas;
  3. sem elegíveis, relato sem escolher.
* **P5:** só sensibilidade. Não muda a escolha.

## 7. Regras
Zero chamadas novas. Nada publicado, sem push, sem Modal.
