# Pré-registro: corte de schema no migration guard

Versão 1.0, congelada em 2026-10-11. Foi escrita antes de qualquer chamada ao Ekbasis neste trabalho e antes de montar
os estados do T2 e do T3. O sha256 vai ao líder antes da primeira chamada. Desvios vão em `DEVIATIONS.md`; este arquivo
não muda depois do hash.

## 1. O que muda em relação ao pedido, e por quê

O pedido supunha que o `build_state` do 0.1.17 manda o schema inteiro ao modelo. **Não manda.** Ele já faz um corte,
mas um corte por regex:

* entram as tabelas cujo nome aparece em qualquer lugar do texto da migração, inclusive dentro de strings;
* entram também os vizinhos por FK dessas tabelas, a 1 salto;
* tudo isso tem teto de `MAX_TABLES = 8`, na ordem do catálogo;
* as demais tabelas viram uma linha "Other tables" com até 40 nomes;
* views, triggers, funções, sequências e domínios não entram.

Por isso, "mandar só o que importa para economizar tokens" deixa de ser a pergunta principal. A pergunta passa a ser
de **precisão do corte**: um corte por parser, que mostra o que a migração realmente toca e o que depende disso, é pelo
menos tão bom quanto o corte por regex com teto de 8? Avisei o líder antes deste pré-registro.

Dois ajustes de desenho decorrem disso, ambos decididos no desenvolvimento e sem modelo:

* **Fallback.** Quando o parser não consegue seguir a migração, o estado volta a ser o do 0.1.17 (regex, teto de 8),
  e não o schema inteiro, que nunca foi mandado. O schema inteiro estouraria o `MAX_CHARS` justamente nos projetos
  grandes.
* **Vizinhos em uma linha.** Cada vizinho por FK aparece numa linha, com a chave, a ação ON DELETE e o NOT NULL das
  colunas, mais a sua linha de contagem em "Rows". Não aparece o DDL completo. A primeira versão, com DDL completo dos
  vizinhos dentro de um orçamento de 24 mil caracteres, deixava o estado 2 a 3,5 vezes maior que o OLD nos casos
  reais. Num caso, chegava a 57 mil contra 18 mil.

## 2. Produto

* **OLD:** `main` do ekbasis em `ec91a41` (0.1.17), sem mudança.
* **NEW:** branch local `schema-pruning`, commit `fab1d95`, sem push. O código está congelado neste commit. Um
  conserto, se houver, vira desvio datado e o teste é refeito com os dois commits.

**O que o NEW faz** (`schema_cut` e `_cut_state` em `ekbasis/migrations.py`):

* **Catálogo estendido.** Ganha views, com dependências por coluna via `pg_depend`/`pg_rewrite`; triggers não
  internos; funções de trigger (`pg_get_functiondef`); sequências com dono; domínios; e todas as relações com tipo e
  tabela-alvo (índice → tabela, partição → mãe).
* **Parser de referências.** Um tokenizador sobre o SQL fora de strings e corpos encontra:
  * ALTER/DROP/TRUNCATE/LOCK de tabela e CREATE INDEX/TRIGGER/POLICY ... ON;
  * INSERT/MERGE INTO e UPDATE, como comando;
  * listas FROM/JOIN, inclusive de subqueries, CTEs e UPDATE ... FROM;
  * REFERENCES, LIKE, INHERITS e PARTITION OF;
  * ALTER/DROP INDEX e SEQUENCE, resolvidos para a tabela dona;
  * ALTER/DROP TYPE e DOMAIN, que levam às tabelas que usam o tipo;
  * nextval/setval e pg_get_serial_sequence;
  * GRANT ... ON e COMMENT ON;
  * nomes qualificados e entre aspas.
* **Corpos.** Os corpos de DO e de CREATE FUNCTION em sql/plpgsql são lidos sem comentários. Os corpos das funções
  dos triggers das tabelas tocadas também são lidos, e as tabelas que eles escrevem entram como tocadas.
* **Nomes locais.** Não contam como nome não resolvido:
  * os nomes criados pela própria migração (tabelas, views, tipos, sequências, constraints e RENAME TO);
  * as CTEs, as tabelas de transição dos triggers e os catálogos do sistema;
  * nomes sob IF EXISTS;
  * sequências implícitas de SERIAL/IDENTITY.
* **Estado.**
  * As tabelas tocadas aparecem em DDL completo, sem teto.
  * Os vizinhos por FK a 1 salto, nos dois sentidos, aparecem numa linha cada.
  * As views dependentes, transitivamente, aparecem numa linha: "v reads T(colunas)".
  * Os triggers das tabelas tocadas aparecem com o corpo das funções até 20 mil caracteres. Acima disso, vai só o
    tamanho do corpo.
  * Entram também as sequências com dono, os enums e domínios usados e as linhas de "Rows".
  * Por fim, o fato "N other tables omitted: not touched by this migration and not linked to it by a foreign key".
* **Fallback para o estado OLD, com nota** ("schema not cut (motivo)"), em cinco casos:
  * SQL dinâmico (EXECUTE);
  * um comando fora da lista (COPY, CALL, CREATE RULE, DROP SCHEMA/EXTENSION/FUNCTION ... CASCADE etc.);
  * um nome não resolvido;
  * um corpo em linguagem que não seja sql/plpgsql;
  * um estado cortado acima do `MAX_CHARS`.
  Por construção, a cobertura do NEW nunca é menor que a do OLD.
* **O que não muda.** A sondagem no schema, as decisões em código, as perguntas, os limiares (0,5) e o `MAX_CHARS`
  continuam iguais. A chave do `VerdictCache` ganha `cut: CUT_VERSION` (0 com o corte desligado). O hash do schema
  passa a incluir views, triggers, funções, sequências, domínios e relações.
* **Desligar.** `EKBASIS_SCHEMA_CUT=off`, ou `build_state(..., prune=False)`.
* **Testes.** São 5 testes novos offline e 1 com PostgreSQL em `tests/test_migrations.py`, cobrindo o corte, os
  fallbacks, as views, os triggers, os vizinhos e a chave de cache. No `fab1d95`, a suíte inteira dá 259 passed,
  2 skipped, com PG 16 local.

## 3. Desenvolvimento (já visto, sem modelo)

* **D2: as 582 do estudo v1,** reconstruídas pelo produto com o catálogo estendido. Há 530 itens com estado.
  * O estado OLD, montado do catálogo reconstruído, é byte a byte o do v4 nos 539 itens comparáveis. Só bateu depois
    de recriar o cluster com locale C e timezone UTC, como o do v4.
  * Fallback em 5 de 530 (0,9%): 2 por estado longo demais, 1 EXECUTE, 1 DROP FUNCTION CASCADE, 1 DROP SCHEMA
    CASCADE.
  * Tamanho do estado: a mediana vai de 6.235 caracteres (OLD) para 4.238 (NEW). A razão NEW/OLD por item tem mediana
    0,75, p10 0,52 e p90 1,63; o NEW fica mais curto em 402 de 525.
  * Em 59 itens, uma tabela tocada pela migração **não** aparecia no OLD (teto de 8 ou regex). Em 18, o OLD mostrava
    tabelas que o NEW não mostra; vários eram nomes casados dentro de strings, como `INSERT INTO "Feature"` com
    descrição que cita "Team".
  * Views entram em 56 itens; triggers, em 47.
* **Casos reais (34):** reconstruídos como PR com cliente falso, lendo os repositórios de real_cases sem escrever neles
  (`GIT_NO_LAZY_FETCH=1`).
  * Há 2 fallbacks: um EXECUTE em mattermost e um estado longo demais em lemmy.
  * Tamanho: o NEW é menor na maioria dos casos. Nos de lemmy ele cresce de 1,3 a 2,3 vezes, por causa dos corpos de
    funções de trigger.
  * O estado de coder-chat-search-update ficou correto depois do conserto das tabelas de transição.
* **Itens que guiaram consertos do parser no desenvolvimento:**
  * comentários dentro de corpos de DO e de função;
  * IF EXISTS;
  * sequências de SERIAL;
  * tabelas de transição;
  * INSERT depois de uma CTE;
  * FROM dentro de `extract`/`substring`.

## 4. Teste T2: as 184 migrações do v3 (não inferioridade)

**Itens e verdade.** São as 184 de `v4/data/labels_v3.jsonl`, com o rótulo `label_product`: 128 benignas e 56
arriscadas. Arriscada = `lost` ou `fails`. O motivo verdadeiro é `fails` se `fails`, senão `loses`.

**Entradas.** `build_cut.py` reconstrói as 184 pelo caminho do produto, com o catálogo estendido. As estatísticas da
réplica semeada são as de `v4/data/items_v4` (mesma semente). Verificação obrigatória antes de chamar o modelo: o estado
OLD de cada item precisa ser byte a byte o do v4. Se algum diferir, ele é listado em `DEVIATIONS.md` e entra assim
mesmo, porque os dois braços leem as mesmas entradas.

**Braços e regimes.**

* OLD: estado do `main` (`ec91a41`), gerado por um checkout separado desse commit, não pela função copiada.
* NEW: estado do `fab1d95`.
* Regime R (estatísticas da réplica) é o **primário**; regime N (sem réplica, o padrão da Action) é o **secundário**.
  Os dois são decisivos (§6).
* As decisões em código (`schema`, `cannot_foresee` por privilégio ou base suja, `ok_empty`) são iguais nos dois
  braços.
* `cannot_foresee` por tamanho segue o produto de cada braço.

**Chamadas.**

* API hospedada (`EKBASIS_URL=https://openinterp.org/api/v1`), chave de estudo lida de
  `~/.config/ekbasis/study_api_key`, pergunta em `instructions` (as constantes `Q_LOST`/`Q_FAILS`/`Q_HALF` do
  produto), `/v1/systemone`, surface `corte-schema-t2`.
* Concorrência no máximo 2. Em 429 ou 5xx, espera crescente e nova tentativa, até 6 tentativas. Um item que ainda
  falhe é refeito no fim; se persistir, conta como `cannot_foresee` naquele braço (fail closed), e isso é relatado.
* Quando o estado NEW é byte a byte igual ao OLD (fallback), o NEW herda a resposta do OLD, sem chamada nova.
* A ordem das chamadas é embaralhada com semente fixa (`20261011`), alternando os braços, para que a deriva do servidor
  no tempo não favoreça um deles.
* Cache de veredito desligado.

**Veredito** (o do produto, como `v4/score_v4.py`):

* `schema` → arriscado, motivo `fails`;
* `cannot_foresee` → arriscado, motivo errado;
* `ok_empty` → ok;
* fora disso, arriscado se P(fails) ≥ 0,5 (ou se houve erro no schema em autocommit), com motivo `fails`; ou se
  P(lost) ≥ 0,5, com motivo `loses`.

## 5. Teste T3: schemas grandes, repositórios novos (cobertura, sem modelo salvo exceção)

**Repositórios.** Lista fixada aqui, cada um no HEAD do branch padrão no dia da clonagem (o commit é registrado):

1. toeverything/AFFiNE (Prisma)
2. ghostfolio/ghostfolio (Prisma)
3. baptisteArno/typebot.io (Prisma)
4. webstudio-is/webstudio (Prisma)
5. goharbor/harbor (`*.up.sql`)
6. concourse/concourse (`*.up.sql`)
7. chirpstack/chirpstack (Diesel `up.sql`)
8. getfider/fider (SQL puro)

Ficam de fora os repositórios do v1/v3, de real_cases, da P2 e do v4, e qualquer um em Rails.

**Reservas, na ordem:** openfga/openfga, inngest/inngest, sebadob/rauthy, harness/drone. Uma reserva só entra se um
repositório da lista não tiver pasta PostgreSQL encontrada pelos `DEFAULT_GLOBS` do produto, ou se o clone falhar.

**Procedimento.**

* Em cada repositório, entra a pasta de migrações PostgreSQL com mais arquivos encontrada pelos `DEFAULT_GLOBS`, com
  o `SKIP` do produto (sem mysql/sqlite). Os arquivos são aplicados em ordem num scratch, como o produto faz (uma
  transação; em erro, autocommit).
* Para **cada** migração, antes de aplicá-la, registram-se:
  * a decisão em código;
  * os tamanhos dos estados OLD e NEW, em regime N;
  * se cada um passa do `MAX_CHARS`;
  * o motivo de fallback do NEW.

**Medidas.**

* **Primária:** a fração de migrações que hoje dão "cannot foresee" por tamanho (OLD > 60.000) e que o NEW responde
  (NEW ≤ 60.000).
* **Secundárias:**
  * a taxa de fallback do NEW em código nunca visto, com os motivos (generalização do parser);
  * a razão de tamanho NEW/OLD;
  * os itens em que NEW > `MAX_CHARS`.

**Rótulos.** Se houver ao menos um item que passa de OLD-longo para NEW-respondido, cada um desses itens é rotulado por
execução com o executor congelado do estudo (`pr_study/pgexec.py`: 20 linhas semeadas por tabela, a mesma regra de
perda). O NEW é perguntado no regime N, e a acurácia é relatada como descritiva. Sem nenhum item assim, o T3 relata só a
cobertura e diz isso. Nenhum rótulo é inventado.

**Expectativa declarada.** No D2, nenhum estado OLD passou de 30.581 caracteres. Por isso espero **pouca ou nenhuma**
migração OLD acima do `MAX_CHARS`. Se for zero, o resultado do T3 é que o corte não é o que destrava os projetos
grandes: o `MAX_CHARS` hoje estoura por outra coisa, ou não estoura.

## 6. Critérios (T2), decisão e relato

São quatro critérios, avaliados em cada regime (R e N), com o OLD como base pareada:

| | Critério |
|---|---|
| C1 | Acurácia: NEW − OLD ≥ −2 pp (estimativa pontual) |
| C2 | Alarme falso nas 128 benignas: NEW ≤ OLD + 3 itens |
| C3 | Recall nas 56 arriscadas: NEW ≥ OLD − 2 itens |
| C4 | Motivo exato nas arriscadas sinalizadas: NEW ≥ OLD − 2 itens |

**Estatística de C1.**

* McNemar exato bicaudal sobre os discordantes.
* IC 95% pareado da diferença de acurácia por bootstrap de itens: 10.000 reamostras, semente 20261011.
* A decisão usa a estimativa pontual, como os outros três critérios em itens. Se o limite inferior do IC ficar abaixo
  de −2 pp, o README diz explicitamente que a não inferioridade **não foi demonstrada estatisticamente** com n = 184,
  ainda que C1 passe.

**Decisão.**

* Passa nos quatro critérios nos dois regimes: recomendo o corte como padrão (`EKBASIS_SCHEMA_CUT` ligado), com o
  `MAX_CHARS` como rede de segurança.
* Falha em algum: o corte não vira padrão. O código fica no branch, desligado por padrão, e o README diz em qual
  critério falhou e em quais itens.

**Relato obrigatório**, além dos critérios:

* a mediana de tokens de entrada (campo `usage` da API) por braço e a redução mediana pareada;
* a latência por chamada: mediana do tempo de parede e do `Server-Timing`;
* a lista de itens que mudaram de veredito, com o motivo;
* a taxa de fallback no T2;
* o T3 inteiro.
