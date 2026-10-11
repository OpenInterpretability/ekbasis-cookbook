# v4: adendos e desvios (PREREG_v4.md, sha256 924d3703…)

## Adendo 1 (2026-10-11): o produto congelado, antes de qualquer chamada no T1 ou no T2

**Commit congelado do NEW: `5999e53`**, no branch local `constraint-facts`. Ele contém a variante B e a cópia do plugin
sincronizada. O código do pacote é idêntico ao de `018528f`. O OLD é `8071e38`. O branch **não foi enviado** ao
GitHub. 243 testes passam (há 8 testes novos em `TestConstraintFacts`).

### O que o desenvolvimento mudou, dentro do que a §2 permite

Mexi só em redação e em corte de eventos. Nenhuma classe nova.

* **Variante A** (`fb5a6c7`). Era a lista completa da §2, com um fato longo por evento: "PostgreSQL checks it against
  every row…", mais "nothing in this state shows / the statistics do not show whether…".
* **Variante B, a congelada:**
  1. A conversão `ALTER COLUMN ... TYPE` foi **removida** como evento.
  2. O `INSERT ... SELECT` foi **estreitado**: só entra quando a tabela de destino tem UNIQUE, CHECK ou FK. NOT NULL
     e PK sozinhos saem.
  3. A frase "nada mostra / as estatísticas não mostram" foi **removida**. As estatísticas só entram quando **mostram
     violação** (fração de NULL acima de zero; menos distintos que linhas não nulas). As frases que davam segurança
     ("values distinct", "no NULL") também saíram.
  4. O texto ficou curto: "Action K adds … on T, which already holds rows / holds production data; PostgreSQL rejects
     the statement if any existing row violates it." Quando há escrita anterior, acrescenta "Before it, action J
     rewrites c in every row / in the rows its WHERE selects".
  5. Uma conversão `TYPE … USING` passa a contar como escrita anterior da coluna. Isso evita a decisão em código
     errada que apareceu no D2 (formbricks `email_verified`).

### Números de desenvolvimento

**D2.** Itens cujo estado muda. A diferença NEW − OLD é medida só neles, com as respostas desta rodada.

| Variante | Regime | Alarmes novos em benignas | Alarmes removidos em benignas | Arriscadas recém-marcadas | Arriscadas que deixaram de ser marcadas |
|---|---|---|---|---|---|
| A | N | 3 | 3 | 3 | 5 |
| A | R | 5 | 1 | 4 | 16 |
| B | N | 3 | 2 | 3 | 0 |
| B | R | 3 | 2 | 0 | 1 |

* Na variante A, no regime R, os fatos longos **derrubaram** P(falha) em migrações que falham de fato. Exemplo: as
  conversões para jsonb do mattermost, onde os tokens sintéticos não são JSON válido. Por isso a B.
* A decisão em código acertou 4 de 4 no D2 da variante B (regime R). Na variante A tinham sido 5 de 6.

**D1.** Os 34 casos do `real_cases`, variante B, contra as respostas 0.1.12 do `real_cases`.

* **Regime N:** viraram acerto `coder-deadline-check` (P(falha) 0,44 → 0,53), `lemmy-local-image-person` (de motivo
  errado para acerto) e `lemmy-aggregates-deferred` (0,07 → 0,62).
* **Regime R:** nenhum ganho líquido. `lemmy-username-unique` e `calcom-backfill-userid` subiram na variante A e não
  na B.
* **Sem mudança nos dois regimes:** os CHECK e FK puros (lemmy warn, formbricks Display, lemmy person_saved) e o enum
  do rallly continuam abaixo de 0,5.
* **Leitura.** O modelo não passa a acreditar em violação só porque ouviu que ela é possível. Os ganhos aparecem
  quando o fato aponta para uma falha mecânica (DEFAULT que a FK rejeita, linhas que o UPDATE não cobre).

### Rótulos do T2

A reconstrução (`build_v4.py`, mesma semente) dá **0 divergências** contra `labels_v3.jsonl`: sha256 `0cb4470f…`,
conferido.

* Com o PR #18, 14 itens passaram de autocommit para uma transação (`BEGIN` dentro de corpo `$$`).
* Neles os rótulos dos dois regimes são iguais em "arriscada ou não", então a verdade não muda.

### Chamadas de desenvolvimento

Foram cerca de 1.050, todas com a superfície `pr-study-v4-dev`, concorrência 1.

* No D2-A, 13 respostas do NEW no regime R vieram com erro HTTP. Não foram refeitas: a variante foi descartada.

## Adendo 2 (2026-10-11): T1 congelado, antes de qualquer chamada no T1 ou no T2

**Mineração** (`mine_t1.py`, regras do `real_cases` restritas às pastas PostgreSQL da §3.2):

* 119 commits com sinal forte, no máximo 25 por repositório. Todos foram lidos com o diff e o corpo do commit.
* Não usei a API do GitHub nesta curadoria: a evidência é o texto do próprio commit ou o comentário no SQL.

**Incluídos no escopo: 9.** A lista está em `incidents_v4.jsonl`, `set = "T1"`.

| Classe | Quantos | Evidência explícita | Evidência inferida |
|---|---|---|---|
| `fails_data` | 6 | 4 | 2 |
| `fails_schema` | 3 | 1 | 2 |

Seis dos nove têm `constraint_pattern = sim`.

**Fora do escopo ou desconhecidos:** os motivos estão em `curation_v4.json`.

* `fails_env`: 8 (privilégios, schema fixo no código, versão do PostgreSQL, extensão);
* `duration`/lock: 6;
* `unknown`: 15, a maioria reverts sem motivo;
* os demais commits lidos não são incidente: funcionalidade, renumeração, idempotência ou estado do executor.

**Desvio declarado.** O T1 tem **9 < 10** incidentes no escopo. Pela §6, o P1 fica "subdimensionado" e a decisão é do
líder. Para dar mais dados **sem mudar o primário**, acrescento o **T1b, secundário**:

* são os 25 commits seguintes (posições 26 a 50) dos dois repositórios que bateram o teto, windmill e
  sourcegraph-public-snapshot (`mine_t1b.py`);
* o windmill só tinha mais 22;
* foram lidos sob a mesma regra e deram **1 incidente**: `windmill-remove-demo-fk`.

O T1b é decidido antes de qualquer chamada. **O P1 continua calculado só no T1 (n = 9).** O T1 + T1b (n = 10) sai
como secundário.

**Execução sem modelo** (`run_t1.py prep`):

* a base de todos os 10 monta;
* o rótulo sintético falha em 7, perde em 1 e não falha em 2 (`sourcegraph-commit-dates-dup`, porque os dados
  sintéticos não repetem; `windmill-otel-dup`, porque a linha 'otel' não existe na base semeada);
* 3 incidentes falham no próprio esquema (harness, as duas do inbox-zero) e são decididos em código igualmente no OLD e
  no NEW. Na prática o P1 depende dos outros 6 (T1) ou 7 (T1 + T1b).

**Hashes:** `incidents_v4.jsonl` `49322a73…`, `curation_v4.json` `25241d84…`, scripts em `MANIFEST_v4.sha256`.

## Adendo 3 (2026-10-11): resultado

O resultado está em `results_v4.txt`.

| Critério | Resultado |
|---|---|
| P1 | NEW − OLD = 0. **Falha**, e o T1 é subdimensionado: n = 9. |
| P2 | 21/128. Passa. |
| P3 | +3 itens. Passa, no limite. |
| P4 | 54 → 54. Passa. |

**Decisão:** "não melhora o que prometia". O branch fica sem PR. Não houve desvio na execução.
