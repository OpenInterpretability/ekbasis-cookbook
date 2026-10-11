# Pré-registro v4: fatos de constraint (CHECK, UNIQUE, FK, NOT NULL, enum) sobre linhas antigas

Versão 1.0, congelada em 2026-10-11, antes de qualquer chamada a modelo desta avaliação, de desenvolvimento ou de
teste. O sha256 deste arquivo vai ao líder antes da primeira chamada. Desvios vão num adendo datado
(`DEVIATIONS_v4.md`), e este arquivo não muda.

## 1. Pergunta e hipótese

No backtest de incidentes reais (`real_cases`, 2026-10-10), o padrão que mais escapou do guard foi este: **uma
constraint nova, ou uma escrita sob uma constraint existente, que linhas antigas violam**. Os casos:

* CHECK novo: lemmy, warn check;
* UNIQUE ou duplicata ao copiar linhas antigas: lemmy person_saved, cal.com backfill de userId, lemmy username;
* FK nova em coluna povoada: formbricks Display;
* valor de enum usado na mesma transação em que foi criado: rallly.

São 6 dos 8 "missed". O mesmo padrão aparece em 3 dos 5 casos "pego pelo motivo errado" (coder deadline, cal.com
BookingReference, langfuse dashboard). Nesses, o modelo apontou a perda do UPDATE que precede a constraint, e não a
falha da constraint.

**Hipótese.** Quando o estado diz explicitamente, com fatos decididos em código, que a migração impõe uma constraint
sobre linhas que já existem, o modelo acerta mais vezes, e pelo motivo certo, as migrações que falham por isso. O
custo em alarme falso nas migrações benignas fica dentro do orçamento. Os fatos vêm do catálogo, dos statements e das
estatísticas agregadas da réplica (quando há), e nunca de valores.

## 2. A mudança no produto (o que fica fixo agora e o que o desenvolvimento pode mexer)

Ela é feita no branch `constraint-facts` do ekbasis, a partir do `main` em `8071e38`, que já inclui o PR #18 (BEGIN em
corpo de função e goose). A função é pura, do tipo `constraint_facts(catalog, statements, stats) -> (facts, decided)`,
chamada por `_check_file` antes de `build_state`. As linhas que ela produz entram no bloco `Facts:` que o estado já tem.

**Fixo agora:**

1. **Eventos detectados** (em tabelas que existem na base, isto é, não criadas no próprio arquivo):
   * `ADD CONSTRAINT ... CHECK/UNIQUE/PRIMARY KEY/FOREIGN KEY` sem `NOT VALID`;
   * `ALTER COLUMN ... SET NOT NULL`;
   * `CREATE UNIQUE INDEX`;
   * `ADD COLUMN ... NOT NULL` sem DEFAULT;
   * `ADD COLUMN` com DEFAULT não nulo e `REFERENCES` ou `CHECK`;
   * `ALTER COLUMN ... TYPE` (conversão de valores existentes);
   * `INSERT ... SELECT` que copia linhas existentes para uma tabela com UNIQUE, PK, CHECK, NOT NULL ou FK;
   * `UPDATE` de colunas cobertas por UNIQUE, PK, FK ou CHECK existentes;
   * uso, no mesmo arquivo em transação, de um rótulo de enum adicionado antes por `ALTER TYPE ... ADD VALUE`.

   O desenvolvimento pode **remover** eventos desta lista ou estreitá-los. Não pode acrescentar classes de evento
   novas.
2. **Conteúdo do fato.** Cada fato diz:
   * qual constraint, em qual tabela e colunas;
   * que ela vale para as linhas que já existem;
   * se algum statement anterior do mesmo arquivo escreve nessas colunas ou apaga linhas dessa tabela;
   * o que as estatísticas mostram ou deixam de mostrar.

   Com réplica, os números possíveis são a fração de NULL (para NOT NULL e PK) e o número estimado de distintos contra
   as linhas (para UNIQUE e PK de uma coluna). Sem réplica, o fato diz que a tabela tem dados de produção e que nada
   no estado mostra se as linhas atuais satisfazem a constraint.
3. **Nunca valores.** Não entram mínimo, máximo, `histogram_bounds` nem `most_common_vals`. Mínimo e máximo **são
   valores** e quebrariam a promessa do produto ("never reads data values"), por isso a sugestão de min/max fica de
   fora. A consulta `STATS` não muda.
4. **Decisão em código: uma única regra permitida.** Com réplica, um `SET NOT NULL` ou `ADD PRIMARY KEY` numa coluna
   com `null_frac ≥ 0,005`, sem statement anterior no arquivo que escreva essa coluna ou apague linhas da tabela, vira
   `fails` decidido em código ("about X% of the rows are NULL"). Fora isso, o modelo decide.
5. **Não mudam:** as perguntas (texto idêntico), os limiares (0,5 para perda e para falha), a sondagem no esquema
   vazio, as regras de transação e a consulta de estatísticas.

**Livre no desenvolvimento:** a redação dos fatos, os detalhes do parser e o corte de eventos (dentro do item 1).

## 3. Dados

### 3.1 Desenvolvimento (já vistos; servem para ajustar, nunca para decidir)

* **D1.** Os 34 candidatos do `real_cases`, com o mesmo executor (`run_cases.py`), produto antigo e novo, nos braços
  com e sem réplica.
* **D2.** As 582 migrações do estudo v1 (rótulos `label_product` do v2). Servem para medir alarme falso em
  desenvolvimento. São chamadas só as migrações cujo estado muda com o produto novo; as demais herdam a resposta,
  porque o estado é idêntico (ver §5).

### 3.2 Teste (só depois de o produto ser congelado por commit)

* **T1. Incidentes novos.** Vêm de 12 repositórios **nunca usados**:
  * windmill (`backend/migrations`);
  * sourcegraph-public-snapshot (`migrations/frontend`, `migrations/codeintel`, `migrations/codeinsights`);
  * harness (`app/store/database/migrate/postgres`);
  * ente (`server/migrations`);
  * openmeter (`tools/migrate/migrations`);
  * inbox-zero (`apps/web/prisma/migrations`);
  * linkwarden (`packages/prisma/migrations`);
  * openpanel (`packages/db/prisma/migrations`);
  * teable (`packages/db-main-prisma/prisma/postgres/migrations`);
  * authelia (`internal/storage/migrations/postgres`);
  * supabase/storage (`migrations/tenant`, `migrations/multitenant`);
  * atuin (`crates/atuin-server/src/db/postgres/migrations`).

  Ficam excluídos todos os 16 repositórios do `real_cases` e os 12 do estudo.

  **Mineração.** É o `mine.py` do `real_cases` sem mudança: o regex de mensagem forte (`STRONG`), mais edição,
  remoção ou nome de correção.

  **Curadoria, em ordem fixa.** Por repositório, os commits com sinal forte são lidos do mais novo para o mais antigo,
  **até 25 por repositório**. Cada um é incluído se houver texto upstream (commit, PR ou issue) dizendo que a
  migração falhou, quebrou um deploy ou perdeu/corrompeu dados, **ou** se o diff do conserto corrige sem ambiguidade
  um statement que falha ou perde dados em linhas existentes. O primeiro caso é evidência "explícita", o segundo
  "inferida".

  **Classes no escopo:** `fails_data`, `fails_schema` e `loss`. `fails_env`, `duration` e `unknown` são registrados e
  ficam fora. Cada incluído recebe uma marca `constraint_pattern` (sim ou não), definida antes de qualquer execução:
  o conserto mexe numa constraint, numa escrita sob constraint ou num uso de enum sobre linhas existentes.

  **Congelamento.** A lista (`incidents_v4.jsonl`, com classe, evidência, marca e links) e os motivos de cada descarte
  são congelados com sha256 num adendo, **antes de qualquer chamada no T1**. A curadoria acontece **depois** de o
  produto novo ser congelado. Nenhum veredito do guard, antigo ou novo, é visto antes do congelamento.
* **T2. As 184 migrações do v3**, com os rótulos congelados (`labels_v3.jsonl`, sha256 `0cb4470f…`): 128 benignas e 56
  arriscadas.
  * Os estados são refeitos pelo pipeline do v3 (`build_v3.py`, mesmo sorteio e mesma semente), agora gravando as
    entradas cruas de cada item: catálogo do esquema montado pelo papel, statements, estatísticas, transação, erro de
    esquema e decisões em código.
  * Os estados antigo e novo saem dessas mesmas entradas, cada um pelo código da sua versão.
  * Se o rótulo refeito divergir do congelado, vale o congelado e a divergência é relatada.

## 4. Braços e regimes

* **OLD:** `main` em `8071e38`.
* **NEW:** `constraint-facts` no commit congelado (o hash vai no adendo).
* **R (com réplica):** estatísticas do banco semeado, como no v3 e no `real_cases`.
* **N (sem réplica):** o padrão da Action.
* O cache de veredito fica desligado (`EKBASIS_VERDICT_CACHE=off`). API hospedada, chave de estudo, **concorrência
  1**, até 3 tentativas por item.

**Regra de reaproveitamento.** Quando o estado NEW de um item é byte a byte igual ao OLD, as perguntas são as mesmas
e o produto faria a mesma chamada, então o item NEW herda a resposta OLD desta rodada (é o que o cache do produto
faria). Só os itens com estado diferente são chamados no NEW. A taxa de deriva da API é relatada comparando o OLD de
agora com as respostas gravadas do v3 nos mesmos estados.

## 5. Métricas e critérios (confirmatórios)

O "acerto pelo motivo" é o `caught` do `real_cases/table.py`: o guard marca arriscado com o motivo da classe upstream
(`fails_*` → `schema`/`fails`; `loss` → `loses`). `cannot_foresee` não conta como acerto.

| | Critério | Passa se |
|---|---|---|
| P1 | Acerto pelo motivo nos incidentes T1, regime N (primário) | NEW − OLD ≥ 3 itens líquidos, **e** McNemar exato unilateral (pares discordantes) p ≤ 0,10 |
| P2 | Alarme falso nas 128 benignas do T2, regime R | NEW ≤ 23/128 (**≤ 15,6% + 3 pp = 18,6%**) |
| P3 | Alarme falso nas 128 benignas do T2, regime N | NEW − OLD ≤ +3 itens (≤ +2,3 pp; arredondei os 3 pp para baixo) |
| P4 | Proteção: recall nas 56 arriscadas do T2, regime R | NEW ≥ OLD − 2 itens |

**Decisão:**

* P1 a P4 passam: "pronto para PR em main".
* P1 falha e P2 a P4 passam: "não melhora o que prometia". O branch fica sem PR.
* P2, P3 ou P4 falha: "custo alto demais". Sem PR.

**Secundários e exploratórios:**

* P1 no regime R.
* P1 só com evidência explícita.
* P1 só no subgrupo `constraint_pattern`.
* Os "pego pelo motivo errado" que viram acerto.
* As decisões em código: quantas, e quantas certas.
* A regex R3/F1 nos incidentes T1.
* A deriva da API.
* Custo em tokens.

## 6. Poder e ameaças

* **Tamanho do T1.** O tamanho é desconhecido até a curadoria (o `real_cases` deu 25 no escopo em 16 repositórios).
  * Com cerca de 20 incidentes, o P1 só passa se a melhora for concentrada: por exemplo, 4 ganhos e 0 perdas
    (p = 0,0625) ou 5 a 1 (p = 0,109, que falha).
  * Se o T1 tiver menos de 10 incidentes no escopo, o P1 é relatado como "subdimensionado" e a decisão fica com o
    líder.
* **Rótulos sintéticos no T2.** As linhas semeadas são todas distintas, com FKs só para pais semeados, NULL a 25% e
  nenhum valor sentinela.
  * Fatos "nada mostra se as linhas satisfazem" podem custar alarme falso em benignas que, nos dados sintéticos, passam.
    O P2 e o P3 medem exatamente esse custo.
  * Os ganhos de verdade dependem de produção, que nenhum dos dois conjuntos representa.
* **Curadoria por uma pessoa (eu).** Classe e marca são fixadas antes da execução. O viés possível é a favor de falhas
  ruidosas (que viram hotfix).
* **Uma resposta por item.** Sem repetição. A deriva entre a rodada OLD de agora e o v3 é relatada.
* **Desenvolvimento no D1.** Ajustar a redação nos 34 casos já vistos pode sobreajustar a eles. Por isso o T1 é a
  medida.

## 7. Artefatos

* **Pasta:** `scratchpad/v4/`. Contém:
  * este arquivo e `PREREG_v4.sha256`;
  * `MANIFEST_v4.sha256` (scripts, gerado no congelamento);
  * `incidents_v4.jsonl`, `labels_v3.jsonl` (cópia) e as respostas.
* **Commits:** nada no cookbook e nenhum PR para `main` até o resultado.
* **Saída para o líder:** o resultado, com todos os casos, inclusive os que pioraram.
