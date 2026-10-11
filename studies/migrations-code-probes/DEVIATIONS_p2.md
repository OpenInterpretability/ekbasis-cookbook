# P2: adendos e desvios (PREREG_p2.md, sha256 d3075cb2…)

## Adendo 1 (2026-10-11): produto congelado, antes de qualquer chamada de teste

**Commit congelado do NEW: `071c7c7`.** Fica no branch local `code-probes`, sobre `bbcf44c`, sem push. 264 testes
passam: 14 de probe, edição e setup em `tests/test_probes.py`, mais a revisão do teste de edição em
`test_migrations.py`.

### Mudanças de desenvolvimento, dentro da §2

1. **Probe 2 ganhou o lado "origem presente".** As tabelas lidas que estão **vazias** no scratch recebem uma linha
   inventada. É o mesmo mecanismo do item A2 do líder: um SELECT que entrega NULL a uma coluna NOT NULL. Só o erro
   `23502` vira fato. Motivo: o incidente openmeter do v4 (INSERT…SELECT que omite `updated_at`) só aparece com uma
   linha na origem.
2. **Os probes rodam mesmo com a base "incompleta".** Eles só relatam erros de dados (`23502`/`23503`/`23505`), que
   um objeto ausente não produz. Motivo: no sourcegraph, a base é "incompleta" só porque falta `pg_stat_statements`,
   e os probes ficavam desligados.
3. **Linhas inventadas tentam variantes até satisfazer as CHECKs da tabela**, nesta ordem:
   * só as colunas obrigatórias;
   * mais uma FK anulável preenchida (até 3);
   * mais uma coluna citada por uma CHECK (até 4);
   * todas as colunas preenchidas.

   Um INSERT que não insere nada levanta erro, e o probe é abandonado sem fato.
4. **Observações do líder,** já aplicadas:
   * a documentação proíbe `--setup-sql` no modo `--files` em CI de PR de fork;
   * colisão com a própria base ou com o próprio arquivo é decidida pela sondagem do arquivo inteiro (erro real), e o
     probe 1 fica calado. Há um teste end-to-end disso.

### Números de desenvolvimento

**D1, regime N** (incidentes com fato de probe, contra as respostas OLD do v4):

| Incidente | Antes | Depois |
|---|---|---|
| sourcegraph-batch-spec-fk | motivo errado, P(falha) 0,13 | acerto, 0,92 |
| openmeter-subject-updated-at | perdido, 0,25 | acerto, 0,97 |
| windmill-otel-dup | 0,07 | 0,15, continua perdido |
| windmill-ducklake-null | perdido | motivo errado (P(perda) 0,87) |
| calcom-user-password | acerto | acerto |
| coder-created-by-notnull | acerto | acerto, decidido em código no regime R |

**D2** (539 migrações do v1; estado muda em 12 itens no regime R e 8 no N):

* alarmes falsos novos: 0; arriscadas perdidas: 0;
* decisões em código: 4 no regime R, todas certas.

**Chamadas de desenvolvimento:** 46, superfície `pr-study-p2-dev`, entre 17:52 e 18:05 UTC, fora das janelas de
reinício (12:47–12:52 e 14:22–14:27).

### Execução

* **Pausa.** O trabalho ficou parado das ~14:50 às 17:51 UTC: eu esperava a notificação dos builds e só retomei com a
  mensagem do líder. Nada se perdeu, porque os builds já tinham terminado.
* **Desvio: o OLD do T2 é refeito.** O servidor do Ekbasis reiniciou com contexto de 128k (14:22–14:27). Por isso as
  respostas OLD do v4 **não** são reaproveitadas. O OLD do T2 é refeito inteiro nesta rodada (R e N), para OLD e NEW
  saírem do mesmo servidor. A deriva contra o v4 é relatada.
* **End-to-end do C no supabase/auth** (commit c64f331, sem modelo; script e SQL em `e2e_auth.py` e
  `e2e_auth_guard-setup.sql`):
  * **sem setup:** 13 migrações da base falham e o veredito é "cannot foresee";
  * **com setup** (schema `auth`, papel `supabase_auth_admin`, `search_path` do papel do guard): a base aplica
    limpa e o arquivo recebe veredito do modelo;
  * o setup é lido de `ekb-e2e-base:guard-setup.sql`.

## Adendo 2 (2026-10-11, 18:21 UTC): T1 congelado, antes de qualquer chamada de teste

**Mineração** (`mine_p2.py`, as pastas da §3 e até 40 commits por repositório):

* 74 commits com sinal forte. Nenhum repositório bateu o teto: o hyperswitch deu 39.
* Todos foram lidos, com diff e corpo.

**Incluídos: 4** (`incidents_p2.jsonl`, sha256 `510a0664…`):

| Incidente | Classe | Evidência | Observação |
|---|---|---|---|
| lobechat-email-unique | `fails_data` | explícita | |
| lobechat-agent-index-size | `fails_data` | inferida | |
| plunk-contacts-json | `fails_data` | inferida | |
| hydra-nid-drop-constraint | `fails_schema` | inferida | **edição** de migração existente (B) |

**Descartes:** os motivos estão em `curation_p2.json` (`b3dd488d…`).

**O T1 tem 4 < 10 incidentes no escopo.** Pela §5, o P1 fica "subdimensionado" e a decisão é do líder. Mesmo assim, o
P1 é calculado e relatado. Nenhum dos 4 tem o formato dos três probes: são UNIQUE com dados, tamanho de linha de
índice, `jsonb_each` sobre não-objeto e DROP CONSTRAINT de nome inexistente. O resultado do P1 já se espera nulo, e
isto fica escrito **antes** da execução.

## Adendo 3 (2026-10-11, 18:22 UTC): regra de decisão do líder, antes de olhar o T2

Nenhuma resposta do T2 existe ainda, e o build do T2 está em curso, sem modelo. O líder decidiu:

* **O T1 não será ampliado.** O P1 (n = 4) é relatado como subdimensionado.
* **O PR para main sai se o T2 passar em P2, P3 e P4** (sem regressão no v3) e os testes unitários e o end-to-end
  estiverem verdes. B e C entram pelo mesmo critério.
* **A documentação dirá que o ganho em incidentes novos NÃO foi demonstrado** (P1 subdimensionado, n = 4). Os 2 casos
  de desenvolvimento (sourcegraph-batch-spec-fk e openmeter-subject-updated-at) entram como exemplo do mecanismo,
  não como prova.

## Adendo 4 (2026-10-11, 19:16 UTC): rebase sobre a 0.1.19, antes do T2

* **O que mudou.** A 0.1.19 (PR #26, corte de schema) saiu, e o líder pediu o rebase antes do T2.
  * **NEW passa a ser `9b8ab1c`:** o `071c7c7` rebaseado sobre `9caf2b2`.
  * **OLD passa a ser `9caf2b2`** (main, 0.1.19).
* **O conflito foi um só,** na chamada de `build_state` em `_check_file`. A resolução mantém os probes e passa
  `notes=v.notes` como no main. A lógica congelada não mudou: `probes.py` é idêntico, `git diff 071c7c7 9b8ab1c
  -- ekbasis/probes.py` sai vazio, e B e C também não mudaram. Os testes passam: 274.
* **T1 rodado antes do rebase (superado).** Às 18:21–19:10 UTC, com OLD = `bbcf44c` e NEW = `071c7c7`:
  * lobechat-email-unique: ok/ok nos dois;
  * lobechat-agent-index-size: ok/ok;
  * plunk-contacts-json: "loses" nos dois;
  * hydra-nid-drop-constraint: o OLD não dá veredito (a edição só gera nota) e o NEW dá cannot foresee.

  **O T1 é refeito** com `9caf2b2` contra `9b8ab1c`. As duas rodadas são relatadas.
* **T2.** As entradas cruas (`data/items_p2`, construídas com a lógica de probe de `071c7c7`, idêntica) são
  reaproveitadas. Os estados OLD e NEW saem do `build_state` da 0.1.19 (com o corte), e o OLD inteiro é chamado nesta
  rodada.

## Adendo 5 (2026-10-11, 20:35 UTC): resultado

O resultado está em `results_p2.txt`.

* **T1 final** (`9caf2b2` contra `9b8ab1c`): acerto pelo motivo 0/4 → 0/4 nos dois regimes.
  * Os dois lobe-chat continuam "ok" (o UNIQUE com dados e o tamanho da linha de índice não são formatos dos probes).
  * plunk segue "loses" (motivo errado).
  * Na hydra, a edição agora ganha veredito, mas como **cannot foresee**: a base no layout pop do ory/hydra fica
    incompleta, e o erro relatado é o próprio incidente (`constraint ..._key_set_fkey ... does not exist`). O OLD não
    dava veredito nenhum, só uma nota. O guard falha fechado, mas isso não conta como acerto.
  * O T1 rodado antes do rebase deu o mesmo resultado.
* **T2:**

  | | OLD | NEW |
  |---|---|---|
  | Alarme falso, regime R | 20/128 | 20/128 |
  | Alarme falso, regime N | 19/128 | 19/128 |
  | Recall, regime R | 54/56 | 54/56 |

  O estado muda em 5 itens no regime R (2 decididos em código, ambos falham de fato) e em 3 no N. Nenhum veredito
  muda.
* **Critérios:** P1 falha e é subdimensionado. P2, P3 e P4 passam. **A regra do líder (adendo 3) está cumprida:** T2
  sem regressão, 274 testes e o end-to-end verdes.
* **Documentação** (commit `98417a8`, só docs): diz que o ganho em incidentes novos NÃO foi demonstrado e cita os 2
  casos de desenvolvimento como exemplo do mecanismo.
* **Chamadas de teste:** 374 no T2, entre 19:28 e 19:38 UTC, e as do T1. Nenhum erro, fora das janelas de reinício.
* **Nenhum push e nenhum PR.** O PR depende da autorização do líder, porque abri-lo exige publicar o branch.
