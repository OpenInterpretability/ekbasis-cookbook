# Pré-registro v4: o migration guard em Django e Alembic, com migrações reais

Versão 1.0, congelada em 2026-10-11, antes de qualquer chamada a modelo desta avaliação. Desvios vão num adendo datado.

## 1. O que é avaliado

O produto é `ekbasis migrate-gen` + `migrate-check --bundle`, no commit **`af243dd`** do branch
`migration-guard-frameworks` (PR #14).
* **Renderização.** O SQL de cada migração nova vem do próprio framework: Django `sqlmigrate`, Alembic offline
  `upgrade --sql`.
* **Esquema base.** O framework migra um banco descartável e `pg_dump --schema-only` gera o esquema.
* **Decisões em código.**
  * Código que não é SQL vira **cannot foresee**: Django RunPython, ou uma migração Alembic que não renderiza offline.
  * Migração que não gera nenhum statement vira **ok**.
  * Migração que falha no esquema já é **arriscada**, com motivo "schema".
* O resto vai ao modelo, com o estado, as perguntas e a lógica de veredito e motivo da v3 (t_f = t_l = 0,5).
* **Rails fica fora.** É experimental e não está nesta avaliação.

## 2. Amostra (só texto, antes dos rótulos)

* **Projetos.** Cinco projetos open source em PostgreSQL:
  * Django: healthchecks `efcc84b6`, NetBox `3c6fce6`, Wagtail `e18fa11` (só as apps do produto, sem
    `wagtail/test/`);
  * Alembic: Apache Airflow 2.10.5 (pacote), Prefect 3.4.0 (pacote, versões PostgreSQL).
* **Versões.** Django 6.1, Alembic 1.14 e 1.20, Python 3.12.
* **Moldura.**
  * Todas as migrações do projeto, na ordem de aplicação do framework (`forwards_plan` no Django, cadeia de revisões no
    Alembic).
  * Ficam de fora as iniciais (`initial = True` ou sem revisão anterior), as squashed e as de terceiros (Django
    contrib).
* **Estratos**, pelo texto-fonte (`harness.py`, STRATA):
  * **A, "parece destrutiva":** RemoveField/DeleteModel/AlterField/RenameField/RunPython/RunSQL; ou `op.drop_*`,
    `alter_column`, `execute` e `get_bind` no Alembic.
  * **B, "parece arriscada":** constraints, unique, AddField sem null/default; ou nullable=False no Alembic.
  * **C:** o resto.
* **Sorteio.** Semente `20261011:v4:<projeto>`, com teto de A 25, B 10 e C 5. Depois entraram mais 45 de A (semente
  `…:extra`), decididos **antes de qualquer chamada**, porque a primeira construção mostrou poucos positivos. Ficaram
  411 itens sorteados.
* **Exclusões** (as regras do estudo): `untracked_rows` 17, `named_table_not_seeded` 4. São **390 analisados**:
  * Django 235: healthchecks 85, NetBox 73, Wagtail 77;
  * Alembic 155: Airflow 77, Prefect 78.

## 3. Rótulos (por execução, com o próprio framework)

* **Progresso.** Um banco de progresso, aplicado pelo framework como papel sem superusuário e sem linhas, avança
  migração a migração.
* **Em cada item sorteado:**
  1. o banco de progresso é copiado;
  2. a cópia é semeada com o semeador congelado do estudo, 20 linhas por tabela, sem mexer em `django_migrations` e
     `alembic_version`;
  3. a migração roda **pelo framework**, com RunPython e tudo, na semântica de transação dele;
  4. o rotulador congelado do estudo dá `lost`, e `fails` é a exceção do framework.
* **Verdade.**
  * "Arriscada" = falha ou perde: 77 itens (falha 27, perde 50). As benignas são 313.
  * Por framework: no Django, 52 arriscadas de 235; no Alembic, 25 de 155.
  * Motivo verdadeiro: "falha" se falha; senão, "perda".
* **Lado do produto.**
  * Renderizador do produto, rodando dentro do container do projeto, no estado de progresso.
  * Estatísticas do planner tiradas da cópia semeada.
  * Decisões em código feitas como em `check_bundle`.
* **Resultado da construção, antes do modelo:**
  * 238 itens vão ao modelo;
  * 60 dão ok (sem SQL);
  * 92 dão cannot foresee: 72 RunPython e 20 que não renderizam offline.

## 4. Métricas e hipóteses (por framework: Django e Alembic; cada um decide sozinho)

**Linha de base:** regras R3 ou F1 sobre o **SQL renderizado** (sem SQL, as regras dão "ok"), calculadas antes de
qualquer chamada.
* Django: acurácia 0,762, recall 0,654, motivo 0,882, alarme falso 0,208.
* Alembic: 0,768, 0,640, 0,688, 0,208.

| | Métrica | Critério de "passa" (o mesmo da v3) |
|---|---|---|
| P1 | Acurácia arriscada/ok | ≥ 0,85, limite inferior do IC95 ≥ 0,80, **e** acima das regras (IC pareado > 0) |
| P2 | Motivo exato nas arriscadas marcadas (cannot foresee conta como motivo errado) | ≥ 0,85, limite inferior de Wilson ≥ 0,75 |
| P3 | Alarme falso nas benignas (cannot foresee conta como alarme) | ≤ 0,20, limite superior de Wilson ≤ 0,30, **e** menor que o das regras (McNemar p < 0,05) |
| P4 | Recall nas arriscadas | ≥ 0,85 |

* **Decisão:** "pronto para o framework" se P1–P4 passarem nele.
* **Previsão declarada:** a taxa de cannot foresee (24% dos itens, a maioria benigna) torna P1 e P3 difíceis. O
  resultado vai como sair.
* **Secundário e exploratório:**
  * todos juntos;
  * C1, a fração de cannot foresee;
  * as métricas só nos itens que o produto responde (fora cannot foresee);
  * por projeto;
  * custo.

## 5. Procedimento

* **API.** Hospedada, chave de estudo, **concorrência 1**, Server-Timing gravado, até 3 tentativas.
* **Piloto de 10 itens:** só checa o encanamento e entra na análise.
* **Itens sem resposta:** contam como cannot foresee.
* **Segurança da avaliação.** Os projetos rodaram num container com rede (para instalar e para o host semear e ler o
  banco). O código executado é o dos projetos publicados nas versões fixadas, não código hostil. O isolamento do produto
  foi testado à parte (testes com docker no CI).

## 6. Ameaças

* **Dados sintéticos.** Valem as ressalvas do estudo. Aqui pesa mais, porque RunPython roda sobre tokens sintéticos (um
  `json.loads` num token falha).
* **Rótulo literal de perda.** Um RunPython que reescreve uma coluna recém-criada (por exemplo, preencher um slug) "perde"
  os tokens semeados nela.
* **Código atual.** As migrações são renderizadas com o código atual de cada projeto (modelos e dependências de hoje),
  não com o de quando foram escritas. O framework usa o estado histórico das migrações, não os modelos atuais, mas o
  RunPython importa código do projeto.
* **Amostra por framework.** São 2 a 3 projetos por framework, com 25 e 52 positivos: IC largos.
* **Fora desta avaliação:** Airflow e Prefect em pacote (sem PR real), e Rails.

sha256(MANIFEST_v4.sha256) = a871fb8ce5081edb165aad674692ca36fb0b35e2d748d12fc3c278141c1c97ee
product commit: af243ddbe8e25fb6ddba3f8396dfa4c507e6757e
