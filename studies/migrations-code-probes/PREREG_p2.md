# Pré-registro P2: probes em código que provam o mecanismo, migrações editadas e script de preparo

Versão 1.0, congelada em 2026-10-11, antes de qualquer chamada a modelo deste trabalho. O sha256 vai ao líder antes da
primeira chamada. Desvios vão em `DEVIATIONS_p2.md`, e este arquivo não muda.

## 1. Pergunta e hipótese

O v4 (resultado negativo) mostrou duas coisas. Primeiro, dizer ao modelo que "uma linha antiga pode violar" não move a
probabilidade; o que move é **um mecanismo concreto**. Segundo, os incidentes novos escaparam por quatro formatos:

* `INSERT` de uma chave que já existe, sem `ON CONFLICT`;
* subquery escalar que dá NULL numa coluna NOT NULL;
* `DELETE` de linha ainda referenciada por FK;
* `INSERT` que omite uma coluna NOT NULL.

**Hipótese.** Em vez de texto genérico, o guard **executa probes** numa cópia do schema da base e relata o resultado
**com o erro real do PostgreSQL**. Com isso, acerta pelo motivo certo mais incidentes novos, sem estourar o alarme falso
nas migrações benignas.

**Uma regra vale para tudo:** "fails" só é decidido em código quando o erro se reproduz com **linhas reais**, ou quando
as estatísticas da réplica o implicam. Linhas reais, aqui, são as que as migrações da base inseriram no scratch. Quando
o probe precisa de uma linha hipotética, o resultado vai ao modelo como fato, com a condição explícita e o erro.

## 2. O produto

Branch `code-probes` do ekbasis, a partir do `main` atual (`bbcf44c`, 0.1.16), local, sem push.

### A) Probes

Rodam depois da sondagem atual no schema da base, e só quando ela passa. Cada um roda numa cópia do scratch, nunca na
réplica. Na réplica só se leem `null_frac`, `n_distinct` e `reltuples`: nunca valores, nem mínimo e máximo.

1. **Colisão de chave.** Alvo: um `INSERT` sem `ON CONFLICT` numa tabela que já existe na base e tem UNIQUE ou PK.
   * Numa cópia, as ações até o INSERT rodam e o **mesmo INSERT roda duas vezes**.
   * Se a segunda execução falhar com `23505`, entra o fato: "se a tabela já tiver uma linha com a chave que a ação K
     escreve, ela falha com <erro>".
   * Se a **primeira** execução já colidir com linhas reais do scratch, a sondagem atual já decide `schema`; nada muda.
2. **Origem ausente.** Alvo: uma ação que lê tabelas da base que, no scratch, têm linhas inseridas por migrações
   anteriores.
   * Numa cópia, essas tabelas são esvaziadas (`TRUNCATE ... CASCADE`, só na cópia) e o arquivo roda.
   * Se falhar com `23502` (NOT NULL), entra o fato: "se <tabelas> não tiverem as linhas que a ação K lê, ela falha com
     <erro>".
3. **Referência por FK.** Alvo: um `DELETE FROM T`, ou um `UPDATE` das colunas de chave de T, quando outra tabela C
   referencia T por uma FK com `ON DELETE`/`ON UPDATE` igual a `NO ACTION` ou `RESTRICT`.
   * Numa cópia, entra em C uma linha inventada pelo guard que referencia uma linha de T: uma existente no scratch ou,
     se não houver, uma inventada. O arquivo roda.
   * Se falhar com `23503`, entra o fato: "se uma linha de C ainda referenciar uma linha que a ação K apaga, ela falha
     com <erro>".
   * Se o probe não reproduzir, entra o fato do mecanismo: "a FK <nome> de C referencia T com ON DELETE NO ACTION".
   * **Decisão em código, com réplica:** um `DELETE` sem WHERE (ou um `TRUNCATE` sem CASCADE) de T, quando a réplica
     mostra C com linhas (`reltuples > 0`) e a coluna da FK com `null_frac < 1`. Aí existe referência, e decide
     `fails`.

As linhas inventadas seguem regras fixas:

* tipo a tipo, com valores fixos e marcados `ekbasis_probe`;
* DEFAULT quando há; NULL quando a coluna aceita;
* FKs da linha apontam para uma linha existente do pai ou para uma inventada, com profundidade máxima de 2.

Se a inserção da linha inventada falhar, o probe é **abandonado em silêncio**: sem fato e sem decisão.

**Decisão herdada do v4 (com réplica):** `SET NOT NULL` ou PK sobre NULLs da réplica, sem nada antes no arquivo que os
preencha, decide `fails`.

**Do v4 sai** todo o texto genérico ("which holds production data; PostgreSQL rejects…"). Os fatos são só os dos
probes e da FK, com o mecanismo.

### B) Migração editada

Quando o PR **modifica** uma migração que a base já tem:

* o conteúdo novo é avaliado como um arquivo, sobre o schema das migrações da base que vêm antes dela;
* o veredito sai com uma nota: "bancos que já aplicaram <arquivo> não vão rodar esta mudança; o veredito vale para
  bancos que ainda não aplicaram; o Prisma e o golang-migrate podem recusar o checksum ou o estado dirty".

Hoje só sai a nota, sem veredito. **Justificativa:** um banco novo, como CI, staging ou um self-hosted que instala
depois, roda o conteúdo novo, e uma edição que falha quebra exatamente esses bancos. É o caso do coder 000068 no
backtest.

### C) Script de preparo

* A CLI ganha `--setup-sql PATH` e a Action ganha `setup-sql`. É SQL executado pela conexão de admin no banco
  descartável, antes das migrações da base, com `-v guard_role=<papel>` para dar GRANT ao papel das migrações.
* **Segurança:**
  * o arquivo é lido **sempre da ref da base** (`git show BASE:path`), nunca do head do PR, porque roda com
    privilégio;
  * no modo de arquivos (`--files`, sem base), é lido da árvore de trabalho, e a documentação diz isso;
  * papéis criados pelo script ficam no servidor descartável.
* Ele entra na chave do cache de veredito.
* B e C ganham testes unitários e end-to-end. C entra na avaliação só se mexer em veredito; no T1 e no T2, nenhum
  incidente usa setup-sql.

## 3. Dados

### Desenvolvimento (já vistos)

* os 34 casos do `real_cases`;
* os 10 incidentes do v4;
* as 582 migrações do v1 (o D2 do v4).

### Teste T1: incidentes novos

São de 11 repositórios **nunca usados** (nem no estudo, nem no `real_cases`, nem no v4), com as pastas PostgreSQL
abaixo:

* hyperswitch (`migrations`, `v2_migrations`, `v2_compatible_migrations`);
* lobe-chat (`packages/database/migrations`);
* midday (`packages/db/migrations`);
* Zero (`apps/server/src/db/migrations`);
* plunk (`packages/db/prisma/migrations`);
* quickwit (`quickwit/quickwit-metastore/migrations/postgresql`);
* svix-webhooks (`server/svix-server/migrations`);
* posthog (`rust/*migrations*`, só as pastas PostgreSQL);
* graphql-engine (`server/src-rsr/migrations`);
* hydra (`persistence/sql/migrations`, só os arquivos `.postgres.` e os sem dialeto);
* keto (`internal/persistence/sql/migrations/sql`, idem).

**Mineração:** é o `mine_t1.py` do v4 com essas pastas, commits com sinal forte do mais novo ao mais antigo, **até 40
por repositório**.

**Inclusão e classes:** as mesmas do v4.

* No escopo: `fails_data`, `fails_schema` e `loss`.
* Evidência explícita ou inferida, marcada.
* **Novo:** um incidente pode ser uma **edição** de migração existente (o PR do conserto ruim). Nesse caso, o estado
  do PR é o commit que editou.

**Ordem e congelamento:**

1. a curadoria só começa **depois** do commit do produto ser congelado (aviso ao líder);
2. a lista e os descartes são congelados com sha256 antes de qualquer chamada no T1 (aviso ao líder);
3. nenhum veredito é visto antes disso.

### Teste T2: alarme falso

São as 184 migrações do v3, com os rótulos congelados (`0cb4470f…`).

* Os estados OLD são os do 0.1.16. Se forem byte a byte iguais aos de 8071e38, reaproveitam as respostas OLD do v4, e
  o adendo verifica.
* Os estados NEW vêm do pipeline do v3 com a função `_check_file` do NEW, rodada no scratch de cada item. Os probes
  precisam do banco.

## 4. Braços

* **OLD:** `main` em `bbcf44c`. **NEW:** o commit congelado.
* **Regimes:** R (réplica semeada, o seeder do estudo) e N (sem réplica).
* API hospedada, chave de estudo, **concorrência 1, nunca mais de 1 chamada por vez**. Em caso de 429 ou espera, só
  aguardar. Cache de veredito desligado.
* Antes de cada lote, conferir o relógio contra as janelas de manutenção que o líder avisar.
* Quando o estado NEW for byte a byte igual ao OLD, o NEW herda a resposta OLD.

## 5. Critérios (confirmatórios)

O "acerto pelo motivo" é o de sempre: arriscado com o motivo da classe upstream. `cannot_foresee` não conta.

| | Critério | Passa se |
|---|---|---|
| P1 | Acerto pelo motivo no T1, regime N (primário) | NEW − OLD ≥ +3 líquidos **e** McNemar exato unilateral p ≤ 0,10 |
| P2 | Alarme falso nas 128 benignas do T2, regime R | NEW ≤ 23/128 (18,6%) |
| P3 | Alarme falso no T2, regime N | NEW ≤ OLD + 3 itens |
| P4 | Recall nas 56 arriscadas do T2, regime R | NEW ≥ OLD − 2 |

**Decisão:**

* P1 a P4 passam: "pronto para PR".
* Se o P1 falhar, sem PR para A. B e C seguem como PR separado se os testes deles passarem e o P2 a P4 não
  piorarem.
* Se o T1 tiver menos de 10 incidentes no escopo, o P1 é "subdimensionado" e a decisão é do líder.

**Exploratório:**

* o P1 no regime R e só com evidência explícita;
* quantas decisões em código, e quantas certas;
* quantos fatos de probe;
* custo e latência dos probes;
* a regex R3/F1;
* os incidentes de edição (B) à parte.

## 6. Ameaças

* **Tamanho do T1.** O v4 achou 9 em 12 repositórios; aqui o teto é 40 por repositório.
* **Rótulos sintéticos do T2.** Os probes usam linhas inventadas, como o rótulo usa linhas semeadas, então pode haver
  concordância artificial em T2. O P1, nos incidentes reais, é a medida que importa.
* **Linhas inventadas podem não representar produção.** Por isso o fato diz sempre a condição ("se…"), e a decisão
  em código nunca se apoia nelas.
* **Curadoria por uma pessoa.**
* **Uma resposta por item.**
