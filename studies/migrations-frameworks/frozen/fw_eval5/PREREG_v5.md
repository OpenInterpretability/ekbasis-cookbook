# Pré-registro v5: migration guard para Django e Alembic, com `on-code: warn`, em projetos novos

Versão 1.0, congelada em 2026-10-11 antes de qualquer chamada a modelo nesta avaliação. Desvios vão para um adendo
datado.

## 1. O que é avaliado

`ekbasis migrate-gen` + `migrate-check --bundle --on-code warn` no commit **`d96b2ac`** do branch
`migration-guard-frameworks` (PR #14, versão 0.1.15).

Mudanças em relação ao v4 (af243dd), todas antes desta avaliação e sem nenhuma chamada:
* **Política `on-code`** (decisão do líder). O padrão é `warn`. Uma migração com código que não é SQL vira
  **code_not_foreseen**: "revisar à mão", não bloqueia e nunca aparece como "ok". Entram aqui o RunPython do Django e
  a migração Alembic sem SQL offline, porque lê o banco.
* **Renderizador Django.** Coleta o SQL com o loader do `migrate`, que reconhece squash. O `sqlmigrate` falhava com
  `NodeNotFoundError` em projetos que apagaram as migrações já squashed (paperless-ngx).
* **Renderizador Alembic.** Ignora o que a app imprime antes da saída offline. O Superset imprime "Loaded your LOCAL
  configuration".
* Rebase sobre a 0.1.14 (correções de transação e de goose) e cache de veredito.

Estado, perguntas e lógica de veredito e motivo são os da v3. Limiares t_f = t_l = 0,5.

## 2. Amostra nova (projetos nunca usados)

**Django**
* saleor `782a751` (1.457 migrações);
* babybuddy `2f80de4`;
* paperless-ngx `937bf2f`;
* todos com Django 5.2.

**Alembic**
* MLflow 3.1.0 (pacote; a tabela inicial vem do `initial_models`, como faz o MLflow);
* Apache Superset 4.1.2 (pacote, Flask-Migrate; plano e aplicação pelo CLI e pelo app context do Superset).

**Moldura, estratos e sorteio:** iguais aos do v4, com semente `20261011:v5:<projeto>`.
* Tetos: A 25 + 45 extra, B 10, C 5.
* **Segunda extensão.** Mais 150 de A no saleor e no superset (semente `…:extra2`), decidida **antes de qualquer
  chamada**: a primeira construção deixava só 11 e 3 positivos entre os itens respondidos.
* **Total:** 587 sorteados. Saem 16 pelas regras do estudo (`untracked_rows` 11, `named_table_not_seeded` 5) e ficam
  **571**: Django 317 e Alembic 254.

**Rótulos:** mesmo procedimento do v4. O próprio framework executa cada migração, RunPython incluído, sobre uma cópia
semeada do banco de progresso. A verdade é "arriscada" se a migração falha ou perde dados.

**Lado do produto:** mesmo do v4, com a política `warn` mapeada em `analysis_v5.py`.

| Framework | Itens | Ao modelo | ok sem SQL | code_not_foreseen | cannot foresee por outra causa |
|---|---|---|---|---|---|
| Django | 317 | 149 | 92 | 75 | 1 (saleor, falha de render) |
| Alembic | 254 | 129 | 12 | 113 | 0 |

Itens que o produto responde, ou seja, todos menos os code_not_foreseen:

| Framework | Respondidos | Arriscados de verdade | Benignos |
|---|---|---|---|
| Django | 242 | 34 | 208 |
| Alembic | 141 | 13 | 128 |

## 3. Arquivos congelados

| Arquivo | sha256 |
|---|---|
| `data/requests_v5.jsonl` (278) | `8da5ef25a8336e294de2edadd261210568dace44b829ef40216d549181c4b1e8` |
| `data/labels_v5.jsonl` | `413db244afbaa16b490f480be7b81f9e7c53c7319d558454a9afaa6ed3555f5e` |

Os scripts estão em `MANIFEST_v5.sha256`: `harness5.py`, `inner.py`, `convert_v5.py`, `run_v5.py`, `analysis_v5.py`,
o harness congelado do v4 e os itens.

## 4. Métricas e hipóteses (por framework, só nos itens que o produto responde)

**Linha de base:** regras R3 ou F1 sobre o SQL renderizado, nos mesmos itens, calculada antes de qualquer chamada.

| Framework | Acurácia | Recall | Motivo | Alarme falso |
|---|---|---|---|---|
| Django | 0,826 | 1,000 | 0,912 | 0,202 |
| Alembic | 0,773 | 1,000 | 0,846 | 0,250 |

| | Métrica | Critério de "passa" (o da v3) |
|---|---|---|
| P1 | Acurácia arriscada/ok | ≥ 0,85, limite inferior do IC95 ≥ 0,80, **e** acima das regras (IC pareado > 0) |
| P2 | Motivo exato nas arriscadas marcadas | ≥ 0,85, limite inferior de Wilson ≥ 0,75 |
| P3 | Alarme falso nas benignas | ≤ 0,20, limite superior de Wilson ≤ 0,30, **e** menor que o das regras (McNemar p < 0,05) |
| P4 | Recall nas arriscadas | ≥ 0,85 |

**Decisão:** um framework está "pronto com `on-code: warn`" se passar em P1–P4.

**Reportado sem critério de passar:**
* fração de code_not_foreseen: Django 23,7%, Alembic 44,5%;
* recall total, contando code_not_foreseen como "não pego";
* verdade dentro dos code_not_foreseen: no Django, 24 de 75 são arriscados; no Alembic, 29 de 113.

O recall total é, por construção, no máximo:
* Django: 34/58 = 0,586;
* Alembic: 13/42 = 0,310.

São perdas e falhas que ficam para revisão humana, sinalizadas.

**Poder:** o Alembic tem só 13 positivos entre os respondidos. P2 e P4 têm IC de Wilson largos ali (com 13 de 13,
o limite inferior fica em ~0,77), e isso vai declarado.

## 5. Procedimento

* API hospedada, concorrência 1, Server-Timing, até 3 tentativas por chamada.
* Piloto de 10 itens; as respostas entram na análise.
* Item sem resposta conta como cannot foresee.
* Ambiente da avaliação igual ao do v4: projetos publicados, versões fixadas, container com rede.

## 6. Ameaças

* As do v4: dados sintéticos e rótulo literal de perda.
* **Superset:** muitas migrações leem o banco e não têm SQL offline (109 de 227). O Superset domina a fração de
  code_not_foreseen do Alembic.
* **Respondidos:** só os itens que o produto responde entram nas métricas. É a pergunta que o líder fez, e a cobertura
  vai reportada à parte.
* **Renderizadores ajustados no mesmo período:** squash no Django, preâmbulo no Alembic. Os dois ajustes vieram de
  falhas de renderização, sem olhar rótulos nem chamadas.

sha256(MANIFEST_v5.sha256) = 83e23be73d870dcce316332a3b3aea80717804c66265ce19e1c4e7c339b4892f
product commit: d96b2ac7a493ae05946bab6f5b659b26d193f888
