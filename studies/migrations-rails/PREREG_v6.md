# Pré-registro v6: migration guard para Rails, com `on-code: warn`

Versão 1.0, congelada em 2026-10-11, antes de qualquer chamada a modelo nesta avaliação. Qualquer desvio vai para um
adendo datado.

## 1. O que é avaliado

O renderizador Rails de `ekbasis migrate-gen` (hoje atrás de `EKBASIS_EXPERIMENTAL_RAILS=1`) e `migrate-check
--bundle --on-code warn`, no commit **`ea60549`**. Esse commit é o main com o PR #14 (0.1.15) mais o PR #20. O PR #20
não toca no Rails.

* **Como o renderizador funciona.** O Rails não tem modo offline. As migrações novas rodam no esquema base, sem linhas,
  e o SQL que elas enviam é capturado. Ficam de fora as leituras e a contabilidade do Rails (`schema_migrations`,
  `ar_internal_metadata`).
* **Ruby que vai além da DSL de esquema** vira **code_not_foreseen**: models, `find_each`, `update_all` em classes, laços
  (`frameworks.rails_ruby_ops`). Fica para revisão humana e não bloqueia.
* **Migração que falha ao renderizar** vira **cannot foresee** (risky). Exemplo: uma migração que precisa de Redis,
  porque o gerador do produto só alcança o PostgreSQL.
* **Estado, perguntas e lógica de veredito e motivo** são os da v3/v5. Os limiares são t_f = t_l = 0,5. A regra de
  transação é "as Rails runs it": uma transação por migração, salvo `disable_ddl_transaction!`.

## 2. Amostra

**Projetos.** Ambos rodam em PostgreSQL:
* **Mastodon** `9e3fab2`: Rails 8.1.4, Ruby 4.0.7, 617 migrações, sendo 537 em `db/migrate` e 80 em `db/post_migrate`.
  Só `db/migrate` é elegível, que é o que o produto descobre.
* **Maybe** `77b5469`: Rails 7.2.2.1, Ruby 3.4.4, 199 migrações.

**Loomio** ficou de fora antes do sorteio. As migrações mais antigas dele herdam `ActiveRecord::Migration` sem versão,
e por isso o histórico não pode ser reaplicado a partir de um banco vazio.

**Moldura, estratos e sorteio:** os mesmos do v4/v5. A semente é `20261011:v6:<projeto>` e os tetos são A 25 + 45, B 10
e C 5. Os estratos Rails vêm do texto-fonte (`harness_rails.py`, STRATA["rails"]):
* **A:** remove/drop/change/rename/execute/update_all/find_each...
* **B:** `null: false`, índices únicos, chaves estrangeiras, check constraints.

**Resultado:** 170 sorteados, 85 por projeto. Dois saem pelas regras do estudo, um por `named_table_not_seeded` e um por
`untracked_rows`, e ficam **168**.

**Rótulos.** O próprio Rails executa cada migração numa cópia semeada do banco de progresso (`ctx.run(:up, version)`,
com os callbacks e o Ruby da migração). Os rótulos são `lost` e `fails`. O lado do rótulo alcança um Redis na rede da
avaliação, porque o Mastodon usa Redis em migrações. O lado do produto não alcança.

**Lado do produto.** O renderizador do produto roda em uma cópia descartável do banco de progresso, já que ele executa a
migração. Depois vêm as decisões em código de `check_bundle` e as estatísticas do planner tiradas da cópia semeada.

| | Itens | Ao modelo | code_not_foreseen | Cannot foresee (falha de render) |
|---|---|---|---|---|
| Todos | 168 | 138 | 28 (16,7%) | 2 |

* **Verdade:** 50 arriscadas e 118 benignas.
* **Respondidas** (tudo menos code_not_foreseen): 140, com 41 arriscadas.
* **Por projeto:** no Maybe, 34 das arriscadas respondidas; no Mastodon, 7.

**Previsão pedida pelo líder** (fração de code_not_foreseen). Pela experiência do v5, eu esperaria de 20% a 35%. O valor
**observado na construção, antes de qualquer chamada, é 16,7%**. Registro os dois.

## 3. Arquivos congelados

| Arquivo | sha256 |
|---|---|
| `data/requests_v6.jsonl` (138) | `a8a8e04c9abd0f541941a6b796a7f8bb8cc78cbcc2042e3d75cce5ccdbb30a31` |
| `data/labels_v6.jsonl` | `378678ed7df12586a16d8cab59ac84c0797c8b05b0cd4686c5664f29ec0baadc` |

Os scripts estão em `MANIFEST_v6.sha256`: `harness_rails.py`, `ekh_rails.rb`, `convert_v6.py`, `run_v6.py`,
`analysis_v6.py`, além do harness e da análise congelados do v4/v5 e dos itens.

## 4. Métricas e hipóteses (só nos itens que o produto responde)

**Linha de base.** Regras R3 ou F1 sobre o SQL renderizado, nos mesmos 140 itens, calculadas antes de qualquer chamada:
acurácia 0,607, recall 0,927, motivo 0,789 e alarme falso 0,525.

| | Métrica | Critério de "passa" (o mesmo da v3) |
|---|---|---|
| P1 | Acurácia arriscada/ok | ≥ 0,85, limite inferior do IC95 ≥ 0,80, **e** acima das regras (IC pareado > 0) |
| P2 | Motivo exato nas arriscadas marcadas | ≥ 0,85, limite inferior de Wilson ≥ 0,75 |
| P3 | Alarme falso nas benignas | ≤ 0,20, limite superior de Wilson ≤ 0,30, **e** abaixo das regras (McNemar p < 0,05) |
| P4 | Recall nas arriscadas | ≥ 0,85 |

**Decisão:** se P1–P4 passarem, o Rails sai da variável de ambiente e é documentado como suportado. Se não, continua
experimental, com os números na documentação.

**Reportado sem critério de passar:**
* a fração de code_not_foreseen;
* a verdade dentro dela (9 de 28 arriscadas);
* o recall total, contando code_not_foreseen como não pego (no máximo 41/50 = 0,820).

## 5. Procedimento

* API hospedada, chave de estudo, **concorrência 1**, Server-Timing gravado e até 3 tentativas por item.
* Piloto de 10 itens; as respostas dele entram na análise.
* Item sem resposta conta como cannot foresee.
* A API divide GPU com o GLM de produção.

## 6. Ameaças

* **Valem as do v4/v5:** dados sintéticos e rótulo literal de perda.
* **Concentração.** O Maybe concentra os positivos respondidos (34 de 41), e o Mastodon tem poucos (7). O resultado
  pesa mais o Maybe.
* **Esquema vazio.** O renderizador Rails executa a migração num esquema sem linhas. O SQL de um `UPDATE` ou `execute`
  sai igual, porque o Rails o envia mesmo sem linhas. Já um laço Ruby sobre linhas não envia nada. Esses laços só
  viram code_not_foreseen quando o padrão é reconhecido (`rails_ruby_ops`); senão, o produto vê só o SQL que sobrou.

sha256(MANIFEST_v6.sha256) = 1b0ad5d895f8f5183c1384dd7267fcb70a941e41e7fafba483806f68c04632b1
product commit: ea60549518d96fc2ce676f64f9e96504f5ed88b0
