# Pré-registro: o migration guard do Ekbasis continua acertando com estado longo?

Escrito em 2026-10-11, antes de qualquer chamada a modelo deste estudo. O sha256 deste arquivo vai para o "main" antes
da primeira chamada. Os hashes do código, da lista de itens e dos estados ficam em `MANIFEST.sha256`.

## 1. Pergunta e decisão

O Ekbasis-27B foi treinado e avaliado com estados de 0,7 a 1,6 mil tokens. O servidor aceita hoje até 131.072 tokens,
e o migration guard responde "cannot foresee" acima de `MAX_CHARS` = 60.000 caracteres. **A pergunta é se o veredito do
guard continua não-inferior ao do estado nativo quando o bloco de schema do estado fica longo.** A resposta define o
teto a servir e a anunciar, e o novo `MAX_CHARS`.

## 2. Itens e rótulos

* **Os 184 itens do v3**: 56 arriscados (35 perdem dados, 21 falham) e 128 benignos. Os rótulos vêm de
  `v4/data/labels_v3.jsonl` (`label_product`, por execução), e a verdade é a mesma do v3/v4: arriscado = lost ou fails.
* **Entradas do produto**: catálogo, statements, estatísticas da réplica e modo de transação, de `v4/data/items_v4/`.
  O regime é o **R** (réplica semeada), que é o do resultado de produto do v3 (alarme falso de 15,6%).
* Todos os 184 precisam do modelo nesse regime. Nenhum é decidido em código.

## 3. Estados

O código é `states_long.py`, que reproduz `ekbasis.migrations.build_state` da 0.1.17 (`build_state` e
`_transaction_for` estão iguais desde `8071e38`).

* **L0**: o estado do produto. O código confere, byte a byte, que ele é igual a `build_state` e ao estado do v4
  (`st/req_t2_old.R.jsonl`) nos 184.
* **Alongamento**: entram no bloco de schema tabelas **distratoras**, que são tabelas reais dos **outros** projetos.
  * Elas vêm do maior catálogo de cada um dos 11 projetos (v1/v3: calcom, cratesio, documenso, formbricks, hoppscotch,
    langfuse, lemmy, mattermost, triggerdev, umami e vaultwarden).
  * O formato é o do produto: a DDL de `M.ddl` no bloco de schema e a linha de `M.table_facts` em "Rows:", com as
    estatísticas da réplica semeada do próprio projeto. Os enums das distratoras entram na linha "Enum types:".
  * **Nunca entra uma tabela do projeto do item.**
  * **Nada pode colidir.** Uma distratora fica de fora quando:
    1. o nome dela, sem diferença de maiúsculas, coincide com uma tabela ou um enum do catálogo do item;
    2. ela tem FK para uma tabela com nome do catálogo do item;
    3. o nome dela aparece no texto da migração (pela mesma regex de `named_tables`);
    4. o nome repete o de outra distratora já escolhida;
    5. ela usa um enum de mesmo nome que o de outro projeto já escolhido.
  * **Ordem**: os projetos vêm numa ordem sorteada por item (semente `ctxlong:20261011:<id>`), e as tabelas seguem a
    ordem do catálogo dentro de cada projeto. É um banco com os schemas de várias aplicações, sem texto sintético nem
    repetição.
  * O cabeçalho do bloco nas condições longas vira "Schema (the tables the migration names, the tables linked to them
    by foreign keys, and other tables of the database):". O de L0 diria que toda tabela mostrada é nomeada ou ligada,
    o que deixaria de ser verdade. A condição **L0h** (L0 com esse cabeçalho e sem distratoras) mede o efeito só do
    cabeçalho.
* **Comprimento**: tokens contados com o tokenizer do próprio modelo (`tokenizer.json` do repositório
  Ekbasis-27B-INT4). O estado é o mais longo que fique com **≤ alvo − 500** tokens, deixando 500 para a pergunta e o
  template de cada sequência. Os alvos são **16k, 32k, 64k e 120k** (120.000 < 131.072).
  * O servidor lê o estado uma vez por pergunta. O usage de um pedido é ≈ 2 × (estado + ~250).
* **Profundidade**: as tabelas relevantes do produto (as que `build_state` mostra) ficam juntas, como bloco, e as linhas
  de "Rows:" seguem a mesma ordem.
  * Em 16k e 32k ficam no **meio**: metade dos caracteres das distratoras antes delas.
  * Em 64k e 120k ficam no **início**, no **meio** ou no **fim**. Cada item recebe uma profundidade, balanceada dentro
    dos arriscados e dentro dos benignos, em ordem de sha256; ela é a mesma em 64k e 120k (61 ou 62 itens por
    profundidade).
  * **Desvio do desenho sugerido, com justificativa**: a sugestão punha cada item nas três profundidades. A 64k e 120k,
    isso custa ~1,1 M de usage por item. Com a profundidade entre itens, o critério principal por comprimento usa
    todos os itens, e o efeito da profundidade fica descritivo (n ≈ 61 por célula).
* **Perguntas**: `Q_LOST` e `Q_FAILS`, exatas, de `ekbasis/migrations.py`. **A `Q_HALF` não é enviada.**
  * Ela não entra no veredito (`FileVerdict.kind` usa só p_fail e p_lost).
  * Cada pergunta é uma sequência separada no servidor, então tirar a `Q_HALF` não muda as outras duas.
  * O ganho é 1/3 do usage nos 24 itens em autocommit.

## 4. Veredito e métricas

* **Veredito** (regra do produto, em código): arriscado se p_fails ≥ 0,5 ou p_lost ≥ 0,5. Num item em autocommit que
  falha no schema vazio, p_fails = 1, como em `_check_file`.
  * Pedido sem resposta depois das tentativas = "cannot foresee" = arriscado (fail closed, como o produto). Também
    reporto quantos são.
* **Por comprimento L, pareado com L0 nos mesmos itens**:
  * acurácia do veredito, com a queda e o IC de 95% por bootstrap pareado (10.000 reamostragens de itens, semente
    20261011, percentil);
  * McNemar exato bilateral nos discordantes;
  * recall (em itens) e alarme falso (em itens);
  * AUROC de `Q_LOST` contra `label_product.lost` e de `Q_FAILS` contra `label_product.fails`, com o IC da diferença
    por bootstrap;
  * Brier e ECE (10 faixas iguais) por pergunta;
  * a distribuição de |Δp| (mediana, p90, máximo, fração > 0,10, cruzamentos de 0,5);
  * em 64k e 120k, tudo isso por profundidade (descritivo).

## 5. Execução e orçamento

* Cliente `ekbasis` 0.1.17, `EKBASIS_URL=https://openinterp.org/api/v1`, chave de estudo lida de arquivo e nunca
  impressa. Timeout de 600 s. `run_long.py`, com o surface `study-context-length`.
* **Concorrência**: 2 abaixo de 64k e 1 em 64k e 120k. Com HTTP 429 ou 503, espera 60 s e tenta de novo, até 20 vezes,
  sem aumentar a concorrência. Outros erros: 3 tentativas.
* **Cache**:
  * **Latência a frio**: 5 itens fixos (ordem de sha256), em L0 e nos quatro comprimentos, com profundidade "fim". As
    distratoras são rotacionadas com semente própria, e a primeira tabela de cada pedido frio é diferente da de todos
    os outros pedidos frios. Esses 25 pedidos rodam **primeiro**, antes de qualquer outro, então não há prefixo em
    cache além da linha de regras.
  * **No resto**, o cache de prefixo entre itens é permitido (cabeçalho e regras repetem) e fica registrado.
* **Orçamento** (usage de entrada, ≤ 50 M; `run_long.py` para sozinho antes de passar de 50 M). Ordem fixa:
  1. frio (≈ 2,3 M);
  2. L0 (≈ 0,9 M);
  3. L0h (≈ 0,9 M);
  4. 16k nos 184 (≈ 5,8 M);
  5. 32k nos 184 (≈ 11,6 M);
  6. 64k nos 184 (≈ 23,4 M);
  7. 120k (≈ 0,24 M por item) numa ordem fixa: arriscados e benignos ordenados por sha256 e intercalados na proporção
     56:128, de modo que todo prefixo da lista sai estratificado (`data/order_120k.txt`). Roda até o orçamento acabar.
     Se o "main" autorizar mais orçamento antes ou durante a execução, a 120k segue na mesma ordem até o novo teto,
     e isso fica registrado.

## 6. Critérios de não-inferioridade (por comprimento L, contra L0, nos mesmos itens)

* **C1**: queda de acurácia ≤ 2 pp **e** limite superior do IC de 95% da queda ≤ 4 pp.
* **C2**: queda de AUROC ≤ 0,02 em `Q_LOST` e em `Q_FAILS` (estimativa pontual).
* **C3**: recall(L) ≥ recall(L0) − 2 itens.
* **C4**: alarme falso(L) ≤ alarme falso(L0) + 3 itens.

L passa se cumprir C1 a C4 **com os 184 itens**. Uma condição com subamostra (a 120k, se o orçamento não cobrir os 184)
é **exploratória** e não pode virar teto: os limites em itens de C3 e C4 foram pensados para n = 184.

**Decisão**: o teto é o maior L que passa, desde que todos os L menores também passem. Esse L vira a recomendação de
teto servido e anunciado.

**Novo `MAX_CHARS`**: `floor((L − 500) / q99)`, onde q99 é o percentil 99 de tokens por caractere nos 184 estados L0,
que são estados reais do produto. Assim um estado real abaixo do limite cabe em L com folga, e eu reporto também o
valor pela mediana. Se nenhum L passar, a recomendação é manter o teto atual.

**Exploratório, sem decisão**:
* o efeito da profundidade;
* L0h contra L0;
* a latência a frio por comprimento: tempo total e tempo de modelo do Server-Timing;
* a latência com cache nas condições pareadas;
* o motivo do veredito.

## 7. Secundário (intent_check com histórico longo)

Só roda se sobrar orçamento depois do §5. Se rodar, ganha um adendo próprio com hash **antes** da primeira chamada,
usando só itens públicos já existentes (TS-Bench/AgentDojo), sem escrever conteúdo de ataque.

## 8. Ressalvas conhecidas de antemão

* **O que se testa é um schema longo, não uma migração longa.** O produto mostra no máximo 8 tabelas (`MAX_TABLES`) e
  lista as outras só por nome. Hoje, um estado longo vem de uma migração com muitos statements ou de uma mudança futura
  que mostre mais schema. Statements longos não são testados aqui.
* **As distratoras vêm dos mesmos 11 projetos do estudo**, com 20 linhas semeadas cada uma, como as tabelas
  relevantes. Um schema real grande teria estatísticas mais variadas.
* **O tamanho é pequeno para efeitos raros.** São 21 itens que falham, e a AUROC de `Q_FAILS` é ruidosa.
