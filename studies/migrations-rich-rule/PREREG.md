# Pré-registro: regra rica (R_RICH) contra o Ekbasis 0.1.20 no migration guard

Versão 1.0, 2026-10-11, escrita ANTES de qualquer linha da regra e antes de abrir os rótulos do v3. O sha256 deste
arquivo vai ao líder ("main"). Desvios vão para `DEVIATIONS.md`, datados; este arquivo não muda.

## 1. Pergunta

Uma regra escrita a partir da documentação do PostgreSQL, que recebe **os mesmos fatos estruturados** que o estado do
Ekbasis 0.1.20 mostra, empata com o Ekbasis em prever se uma migração **falha** ou **perde dados** num banco com
dados? Nos pilotos de Kubernetes (v2) e dbt, uma regra assim empatou ou venceu. Aqui se testa se o mesmo vale para
migrações.

## 2. Braços

* **EKB**: Ekbasis 0.1.20 (`ekbasis` commit `2093531`), as respostas já gravadas. Composição primária: a mesma que
  produziu o "NEW" de `p2/results_p2.txt` (162/184 em R, 163/184 em N): estados `p2/st/t2_new.{R,N}.jsonl`;
  respostas de `p2/ans/t2_old.{R,N}.jsonl` quando o estado 0.1.20 é idêntico ao 0.1.19 do p2, e de
  `p2/ans/t2_new.{R,N}.jsonl` nos itens que mudaram (5 em R, 3 em N).
  * Motivo de não usar `corte_schema/data/ans_t2.jsonl` como primário: verifiquei (sem rótulos) que os estados do p2
    e os do corte_schema diferem em 183 de 184 itens, e que as duas composições discordam no veredito em 10 itens
    (R) e 9 (N). Os fatos brutos que a regra recebe (`p2/data/items_p2`) são os mesmos que geraram os estados do p2,
    então só a composição do p2 garante "mesmos fatos" para os dois braços, do mesmo servidor. A composição sugerida
    pelo líder (ans_t2 braço new + p2 nos itens mudados) é relatada como **sensibilidade**.
* **R_RICH**: `rule.py`, escrita por mim a partir da semântica documentada do PostgreSQL. Devolve `fails`, `loses`
  ou `ok` por migração. Nenhuma chamada nova ao Ekbasis.

## 3. Os fatos que a regra recebe (os mesmos do estado)

Uma função `view(raw, regime)` em `facts.py` é a ÚNICA porta da regra para os dados. Ela expõe:

* `tool`, `transaction` (o modo que o produto decidiu), os statements (`split_sql` do produto) e `schema_error`
  (o erro do arquivo rodado no schema vazio; o estado mostra isso como fato em autocommit);
* o catálogo da base antes da migração (tabelas: colunas, tipos, NOT NULL, DEFAULT, gerada; constraints;
  índices; enums; domínios; views e suas dependências; triggers e corpos; sequências). A regra só consulta objetos
  que a migração alcança e seus vizinhos por FK, que é o que o corte do estado mostra;
* estatísticas da réplica (regime R apenas), **reduzidas exatamente ao que `table_facts` imprime**: contagem
  arredondada de linhas (ou "nunca analisada"), "about X% NULL"/"a few NULL", "all values distinct", "about k
  distinct values" para k ≤ 10. Nada além disso (nem null_frac cru, nem n_distinct fora dessas faixas). No regime
  N: nada; cada tabela "holds production data (row count unknown)";
* os fatos dos probes (`probe_R` / `probe_N`: as frases do produto) e a decisão em código do produto.

A regra **não** recebe `label_tx`, `label_auto`, `empty_errors` nem `seeded_rows` dos itens; o carregador os descarta
antes de qualquer outra coisa.

## 4. Veredito (o mesmo código para os dois braços)

`verdict()` de `p2/score_v4.py`, copiado sem mudança: itens decididos em código pelo produto (`schema`,
`fails_code`, `cannot_foresee`, `ok_empty`) recebem o mesmo veredito nos dois braços (no T2: 2 itens `fails_code` em
R, 0 em N); nos outros, a regra substitui só a chamada ao modelo, entregando `p_fails` e `p_lost` em {0, 1}.
Erro em autocommit no schema vazio força `fails`, como no produto. Arriscado = `p_fails ≥ 0,5` ou `p_lost ≥ 0,5`;
motivo = `fails` se `p_fails ≥ 0,5`, senão `loses`.

Verdade: `label_product` de `v4/data/labels_v3.jsonl`; arriscado = lost ou fails; motivo verdadeiro = fails se
fails, senão loses.

## 5. Desenvolvimento

* Dev = as migrações do v1 reconstruídas no pipeline do p2 (`p2/data/items_d2`, 539 itens com fatos brutos),
  rótulo = `label_tx` se o produto roda em transação, senão `label_auto` (a definição de `label_product`). Os
  rótulos e mecanismos do v1 (`pr_study/data/labels.jsonl`) podem ser lidos à vontade para diagnóstico.
* A regra v0 é escrita da documentação. Depois, **no máximo 3 rodadas de ajuste** no dev (rodada = rodar no dev
  nos dois regimes, ler os erros, mudar a regra). Nunca no v3.
* Congelamento: sha256 de `rule.py` + `facts.py` + `run.py` (`RULE_FREEZE.sha256`), enviado a main ANTES de abrir
  os rótulos do v3. Depois do congelamento, a regra roda no T2 e as predições também são hasheadas
  (`PRED_FREEZE.sha256`) antes da pontuação.

## 6. Métricas (T2, 184 itens; R primário, N secundário)

* acurácia, recall (arriscadas sinalizadas), alarme falso (benignas sinalizadas), motivo exato (entre as arriscadas
  sinalizadas, motivo = verdadeiro);
* McNemar exato bilateral nos discordantes de acerto (EKB certo só / R_RICH certo só);
* IC 95% pareado por bootstrap da diferença de acurácia EKB − R_RICH: 10.000 reamostragens dos 184 itens,
  semente 20261011, percentis 2,5/97,5;
* complementaridade: "R_RICH E EKB" (arriscado se os dois sinalizam; motivo do EKB) e "R_RICH OU EKB" (arriscado se
  um dos dois sinaliza; motivo do EKB quando ele sinaliza, senão o da regra), com as mesmas métricas;
* onde cada um erra: lista dos itens discordantes com o mecanismo (exploratório).

## 7. Critério de decisão (decidido agora, regime R)

Δ = acurácia(EKB) − acurácia(R_RICH), em pontos percentuais:

* **H1, "o modelo agrega além dos fatos"**: Δ ≥ +2 pp **e** limite inferior do IC > 0;
* **empate, "o valor está nos fatos"**: −2 pp < Δ < +2 pp;
* **"a regra é melhor"**: Δ ≤ −2 pp (o IC é relatado, mas não é exigido, como no critério do líder);
* caso não coberto: Δ ≥ +2 pp com IC que inclui 0 → **"inconclusivo, vantagem numérica do modelo"**.

O regime N é relatado com o mesmo critério, como secundário. Nenhuma chamada nova ao Ekbasis está prevista; se
alguma for necessária, concorrência 1, chave de estudo, e entra em `DEVIATIONS.md`.

## 8. Regras

Nada publicado, sem push, sem Modal. Clone próprio do ekbasis em `regra_rica/ekbasis`.
